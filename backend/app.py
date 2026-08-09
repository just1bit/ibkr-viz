"""IBKR Portfolio Viz — multi-tenant Flask backend.

Google OAuth, per-user encrypted IBKR Flex credentials, user-scoped data.
"""

import logging
import os
import time
import uuid
import secrets
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

import yaml
import requests
from flask import Flask, request, jsonify, send_from_directory, session, g, redirect

import storage
import flex_client
import flex_parser
import report_sql

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(BASE_DIR, 'frontend', 'dist')


def load_config():
    cfg_path = os.path.join(BASE_DIR, 'config.local.yaml')
    defaults = {
        # Google OAuth (required for production)
        'google_client_id': '',
        'google_client_secret': '',
        'base_url': 'http://localhost:5123',

        # Session & encryption
        'secret_key': 'CHANGE_ME',
        'flex_encryption_key': 'CHANGE_ME',

        'flex_max_wait': 30,

        # Database (PostgreSQL)
        'postgres_url': '',

        # S3
        's3_bucket': '',
        's3_endpoint': '',
        's3_region': 'us-east-1',
        's3_access_key': '',
        's3_secret_key': '',
        's3_prefix': 'flex_raw/',
        's3_connect_timeout': 3,
        's3_read_timeout': 10,
        's3_total_max_attempts': 3,

        # Durable local cache path. Override to /home/data/flex_cache on Azure.
        'flex_cache_dir': os.path.join(BASE_DIR, 'flex_cache'),

        # Scheduler
        'market_timezone': 'America/New_York',
        'report_ready_hour': 1,
        'fetch_retry_backoff': 3600,
        'fetch_max_failures': 4,
        'refresh_cooldown': 600,
        'scheduler_max_workers': 8,
        'scheduler_enabled': True,

        # Admin
        'admin_emails': [],

        # Server
        'port': 5123,
        'debug': True,
        'log_level': 'INFO',
    }
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            defaults.update(yaml.safe_load(f) or {})

    return _apply_env_overrides(defaults)


def _apply_env_overrides(defaults):
    env = {k.lower(): v for k, v in os.environ.items()}
    cast = {
        bool: lambda v: v.lower() in ('1', 'true', 'yes'),
        int: lambda v: int(v),
        list: lambda v: [x.strip() for x in v.split(',') if x.strip()],
    }
    for key, val in list(defaults.items()):
        ev = env.get(key.lower())
        if ev is None:
            continue
        defaults[key] = cast.get(type(val), lambda v: v)(ev)
    return defaults


config = load_config()

_log_level = getattr(logging, config.get('log_level', 'INFO').upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True,
)

app = Flask(__name__, static_folder=None)
app.logger.setLevel(_log_level)

logger = logging.getLogger(__name__)

app.config.update(
    SECRET_KEY=config['secret_key'],
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_SECURE=config['base_url'].startswith('https'),
)
s3_store = storage.S3Store(config)


@app.after_request
def prevent_private_response_caching(response):
    """Never let browser/proxy caches share one user's private API data."""
    if request.path.startswith('/api/') or request.path.startswith('/auth/'):
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Vary'] = 'Cookie'
    return response

# All report-cycle decisions are made in the market's timezone.
MARKET_TZ = ZoneInfo(config['market_timezone'])

# Google OAuth endpoints
GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    return storage.connect(config)


def return_db(conn):
    storage.return_conn(conn, config)


# ---------------------------------------------------------------------------
# Session middleware
# ---------------------------------------------------------------------------
@app.before_request
def load_session():
    """Validate the server-side session record on every request."""
    if request.path in ('/auth/login', '/auth/callback') or request.path.startswith('/assets/'):
        return

    sid = session.get('session_id')
    uid = session.get('user_id')
    if sid and uid:
        conn = get_db()
        if storage.validate_session(conn, sid, uid):
            g.user_id = uid
            g.session_id = sid
            g._db_conn = conn
            return
        return_db(conn)
    session.clear()


@app.teardown_appcontext
def close_db_conn(exc):
    conn = getattr(g, '_db_conn', None)
    if conn is not None:
        return_db(conn)
        g._db_conn = None


def get_db_g():
    """Return the request-scoped DB connection (set by load_session or on demand)."""
    if hasattr(g, '_db_conn') and g._db_conn is not None:
        return g._db_conn
    conn = get_db()
    g._db_conn = conn
    return conn


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not getattr(g, 'user_id', None):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = getattr(g, 'user_id', None)
        if not user_id:
            return jsonify({'error': 'Authentication required'}), 401
        conn = get_db_g()
        user = storage.get_user_by_id(conn, user_id)
        if not user or not user['is_admin']:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Report date helpers
# ---------------------------------------------------------------------------
def _expected_report_date(now_mkt):
    """Newest report date IBKR should have published by `now_mkt`.

    `now_mkt` must be an aware datetime in the appropriate market timezone.
    """
    days_back = 1 if now_mkt.hour >= config['report_ready_hour'] else 2
    d = now_mkt.date() - timedelta(days=days_back)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime('%Y-%m-%d')


# ---------------------------------------------------------------------------
# Data storage
# ---------------------------------------------------------------------------
def store_report(conn, user_id, data, report_date):
    """Insert one parsed Flex report into the database (no commit)."""
    c = conn.cursor()
    for acc in data['accounts']:
        aid = acc['account_id']

        c.execute('''INSERT INTO accounts
            (user_id, account_id, net_liquidation, cash_balance, stock_value,
             options_value, dividend_accruals, interest_accruals,
             previous_net_liquidation, day_pnl,
             alias, account_type, syep, drip, tax_lot_method, date_opened)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, account_id) DO UPDATE SET
             net_liquidation=excluded.net_liquidation,
             cash_balance=excluded.cash_balance,
             stock_value=excluded.stock_value,
             options_value=excluded.options_value,
             dividend_accruals=excluded.dividend_accruals,
             interest_accruals=excluded.interest_accruals,
             previous_net_liquidation=excluded.previous_net_liquidation,
             day_pnl=excluded.day_pnl,
             alias=excluded.alias,
             account_type=excluded.account_type,
             syep=excluded.syep,
             drip=excluded.drip,
             tax_lot_method=excluded.tax_lot_method,
             date_opened=excluded.date_opened''',
            (user_id, aid, acc['net_liquidation'], acc['cash_balance'],
             acc['stock_value'], acc['options_value'],
             acc['dividend_accruals'], acc['interest_accruals'],
             acc.get('previous_net_liquidation'),
             acc['day_pnl'], acc['alias'], acc['account_type'],
             acc['syep'], acc['drip'], acc['tax_lot_method'],
             acc['date_opened']))

        for h in acc['holdings']:
            c.execute(
                report_sql.POSITION_INSERT_SQL,
                report_sql.position_values(user_id, report_date, aid, h),
            )

        for contribution in acc.get('day_pnl_contributions', []):
            c.execute(
                report_sql.DAILY_PNL_CONTRIBUTION_INSERT_SQL,
                report_sql.daily_pnl_contribution_values(
                    user_id, report_date, aid, contribution
                ),
            )

# ---------------------------------------------------------------------------
# XML local cache (single latest file per user)
# ---------------------------------------------------------------------------
FLEX_CACHE_DIR = config['flex_cache_dir']
os.makedirs(FLEX_CACHE_DIR, exist_ok=True)


def _cache_path(user_id):
    return os.path.join(FLEX_CACHE_DIR, f'{user_id}.xml')


def _read_cache(user_id):
    path = _cache_path(user_id)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return None


def _write_cache(user_id, xml_text):
    path = _cache_path(user_id)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(xml_text)


def _archive_xml_in_background(user_id, report_date, xml_text, *, trigger):
    """Ensure the canonical archive exists without delaying a refresh."""
    if not s3_store.enabled:
        return

    def archive():
        try:
            key, created = s3_store.save_raw_xml_if_absent(
                user_id, report_date, xml_text
            )
            logger.info(
                'Canonical Flex XML %s user=%s trigger=%s report_date=%s key=%s',
                'archived' if created else 'already present',
                user_id, trigger, report_date, key,
            )
        except Exception as e:
            _safe_log_warning(
                user_id, 'CANONICAL_WRITE', str(e), report_date,
                trigger=trigger, source='canonical',
            )

    threading.Thread(
        target=archive,
        name=f'flex-archive-{user_id}',
        daemon=True,
    ).start()


def _accounts_from_data(data):
    return [
        {
            'account_id': account['account_id'],
            'alias': account['alias'],
            'account_type': account['account_type'],
        }
        for account in data['accounts']
    ]


# ---------------------------------------------------------------------------
# Per-user data refresh
# ---------------------------------------------------------------------------
def _safe_log_error(user_id, error_code, error_detail,
                    report_date=None, duration_ms=None,
                    needs_attention=False, trigger='unknown', source='unknown'):
    """Log a fetch error. Never throws."""
    logger.error(
        'Flex refresh failed user=%s trigger=%s source=%s code=%s '
        'report_date=%s duration_ms=%s detail=%s',
        user_id, trigger, source, error_code, report_date, duration_ms,
        error_detail,
    )
    conn = None
    try:
        conn = get_db()
        storage.log_fetch_error(
            conn, user_id, error_code, error_detail,
            report_date, duration_ms, commit=False,
        )
        failures = storage.count_consecutive_failures(conn, user_id)
        if needs_attention:
            storage.set_user_flex_status(
                conn, user_id, 'needs_attention', commit=False
            )
        elif failures >= config['fetch_max_failures']:
            storage.set_user_flex_status(conn, user_id, 'error', commit=False)
            logger.error(
                'Automatic Flex refresh disabled user=%s after %s '
                'consecutive failures',
                user_id, failures,
            )
        conn.commit()
    except Exception:
        logger.exception('Unable to record fetch error for user %s', user_id)
    finally:
        if conn is not None:
            return_db(conn)


def _safe_log_warning(user_id, warning_code, warning_detail,
                      report_date=None, duration_ms=None,
                      trigger='unknown', source='unknown'):
    """Log a recoverable refresh warning to app logs and fetch_log."""
    logger.warning(
        'Flex refresh warning user=%s trigger=%s source=%s code=%s '
        'report_date=%s duration_ms=%s detail=%s',
        user_id, trigger, source, warning_code, report_date, duration_ms,
        warning_detail,
    )
    conn = None
    try:
        conn = get_db()
        storage.log_fetch_warning(
            conn, user_id, warning_code, warning_detail,
            report_date, duration_ms,
        )
    except Exception:
        logger.exception('Unable to record fetch warning for user %s', user_id)
    finally:
        if conn is not None:
            return_db(conn)


def _store_parsed_data(user_id, data, report_date, *, source='unknown',
                       trigger='unknown', duration_ms=0):
    """Store parsed Flex data to DB. Returns error string or None."""
    conn = get_db()
    store_error = None
    try:
        c = conn.cursor()
        c.execute('''SELECT COUNT(*) AS cnt FROM positions
                     WHERE user_id = ? AND date = ?''', (user_id, report_date))
        if c.fetchone()['cnt'] == 0:
            store_report(conn, user_id, data, report_date)

        storage.set_user_last_refresh(
            conn, user_id, report_date, commit=False
        )
        storage.set_user_fetch_at(conn, user_id, time.time(), commit=False)
        storage.set_user_flex_status(
            conn, user_id, 'healthy', commit=False
        )
        storage.log_fetch_success(
            conn, user_id, report_date, duration_ms, commit=False
        )
        conn.commit()
        logger.info(
            'Flex refresh stored user=%s trigger=%s source=%s '
            'report_date=%s duration_ms=%s',
            user_id, trigger, source, report_date, duration_ms,
        )
    except Exception as e:
        conn.rollback()
        store_error = e
    finally:
        return_db(conn)

    if store_error is not None:
        _safe_log_error(
            user_id, 'DB_INSERT', str(store_error), report_date, duration_ms,
            trigger=trigger, source=source,
        )
        return f'Database insert failed: {store_error}'
    return None


def _ingest_cached_xml(user_id, expected, xml_text, source, trigger):
    """Parse and store a cache candidate when it satisfies this refresh.

    Returns a fetch_and_store-compatible result, or None when the cache is
    stale/invalid and the caller should try the next layer.
    """
    try:
        data = flex_parser.parse_flex_xml(xml_text)
    except Exception as e:
        _safe_log_warning(
            user_id, f'{source.upper()}_CACHE_PARSE', str(e), expected,
            trigger=trigger, source=source,
        )
        return None

    report_date = data['date']
    if report_date < expected:
        logger.info(
            'Flex cache stale user=%s trigger=%s source=%s '
            'report_date=%s expected_date=%s',
            user_id, trigger, source, report_date, expected,
        )
        return None

    accounts = _accounts_from_data(data)

    # Restore the fast local layer when canonical storage was the source.
    # The database is deliberately updated before any canonical upload: a
    # slow object store must not hold a user-visible refresh open.
    if source == 'canonical':
        try:
            _write_cache(user_id, xml_text)
            logger.info(
                'Flex cache restored user=%s trigger=%s from=canonical '
                'to=local report_date=%s',
                user_id, trigger, report_date,
            )
        except Exception as e:
            _safe_log_warning(
                user_id, 'LOCAL_CACHE_WRITE', str(e), report_date,
                trigger=trigger, source=source,
            )
    err = _store_parsed_data(
        user_id, data, report_date, source=source, trigger=trigger
    )
    if err:
        return None, False, err, accounts
    if source == 'local':
        _archive_xml_in_background(
            user_id, report_date, xml_text, trigger=trigger
        )
    return report_date, True, None, accounts


def _recover_cached_report(user_id, expected, trigger='unknown'):
    """Try the latest local XML, then exact-date canonical R2."""
    local_read_failed = False
    try:
        xml_text = _read_cache(user_id)
    except Exception as e:
        local_read_failed = True
        _safe_log_warning(
            user_id, 'LOCAL_CACHE_READ', str(e), expected,
            trigger=trigger, source='local',
        )
        xml_text = None

    if xml_text:
        logger.info(
            'Flex cache candidate user=%s trigger=%s source=local '
            'expected_date=%s',
            user_id, trigger, expected,
        )
        result = _ingest_cached_xml(
            user_id, expected, xml_text, 'local', trigger
        )
        if result:
            return result
    elif not local_read_failed:
        logger.info(
            'Flex cache miss user=%s trigger=%s source=local expected_date=%s',
            user_id, trigger, expected,
        )

    canonical_read_failed = False
    try:
        xml_text = s3_store.get_raw_xml(user_id, expected)
    except storage.ObjectStoreReadError as e:
        canonical_read_failed = True
        _safe_log_warning(
            user_id, 'CANONICAL_READ', str(e), expected,
            trigger=trigger, source='canonical',
        )
        xml_text = None

    if xml_text:
        logger.info(
            'Flex cache candidate user=%s trigger=%s source=canonical '
            'expected_date=%s',
            user_id, trigger, expected,
        )
        result = _ingest_cached_xml(
            user_id, expected, xml_text, 'canonical', trigger
        )
        if result:
            return result
    elif not canonical_read_failed:
        logger.info(
            'Flex cache miss user=%s trigger=%s source=canonical '
            'expected_date=%s',
            user_id, trigger, expected,
        )

    return None


def refresh_user_data(user_id):
    """Check DB → local cache → canonical R2. NO IBKR call.

    Used by configure. Returns (report_date, is_new, error).
    """
    conn = get_db()
    try:
        user = storage.get_user_by_id(conn, user_id)
        if not user or not user['flex_token_enc'] or not user['flex_query_id']:
            return None, False, 'Flex credentials not configured'

        tz = ZoneInfo(user['market_timezone']) if user.get('market_timezone') else MARKET_TZ
        now_mkt = datetime.now(tz)
        expected = _expected_report_date(now_mkt)

        c = conn.cursor()
        c.execute('SELECT MAX(date) AS latest FROM positions WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        latest_stored = row['latest'] if row else None

        if latest_stored and latest_stored >= expected:
            return latest_stored, False, None
    finally:
        return_db(conn)

    result = _recover_cached_report(user_id, expected, trigger='recovery')
    if result:
        report_date, is_new, error, _accounts = result
        return report_date, is_new, error

    return None, False, 'No data available'


_refresh_locks = {}
_refresh_locks_guard = threading.Lock()


def _refresh_lock(user_id):
    with _refresh_locks_guard:
        return _refresh_locks.setdefault(user_id, threading.Lock())


def _retry_backoff_seconds(consecutive_failures):
    """Return the 1h/2h/4h/8h retry tier for the current streak."""
    tier = max(1, min(consecutive_failures, config['fetch_max_failures']))
    return config['fetch_retry_backoff'] * (2 ** (tier - 1))


def fetch_and_store(user_id, *, force=False, trigger='automatic'):
    """Run one serialized refresh for a user.

    ``force`` bypasses scheduler backoff, but never bypasses a valid cache.
    """
    with _refresh_lock(user_id):
        try:
            return _fetch_and_store_unlocked(
                user_id, force=force, trigger=trigger
            )
        except Exception as e:
            logger.exception(
                'Flex refresh pipeline crashed user=%s trigger=%s',
                user_id, trigger,
            )
            _safe_log_error(
                user_id, 'REFRESH_CRASH', str(e),
                trigger=trigger, source='pipeline',
            )
            return None, False, f'Refresh failed unexpectedly: {e}', None


def _fetch_and_store_unlocked(user_id, *, force=False, trigger='automatic'):
    """Call IBKR Flex, archive/cache XML, parse it, then store it.

    This is the ONLY function that calls IBKR. Used by:
      - test-flex (user-initiated and synchronous)
      - trigger-refresh (user-initiated and synchronous)
      - scheduled_refresh (hourly automated)

    Returns (report_date, is_new, error, accounts_list).
    """
    logger.info(
        'Flex refresh started user=%s trigger=%s force=%s',
        user_id, trigger, force,
    )
    conn = get_db()
    try:
        user = storage.get_user_by_id(conn, user_id)
        if not user or not user['flex_token_enc'] or not user['flex_query_id']:
            return None, False, 'Flex credentials not configured', None

        flex_token = storage.decrypt_flex_token(config, user['flex_token_enc'])
        query_id = user['flex_query_id']
        tz = ZoneInfo(user['market_timezone']) if user.get('market_timezone') else MARKET_TZ
        now_mkt = datetime.now(tz)
        expected = _expected_report_date(now_mkt)

        c = conn.cursor()
        c.execute('SELECT MAX(date) AS latest FROM positions WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        latest_stored = row['latest'] if row else None

        if latest_stored and latest_stored >= expected:
            c.execute('SELECT account_id, alias, account_type FROM accounts WHERE user_id = ?',
                      (user_id,))
            accounts = [{'account_id': r['account_id'], 'alias': r['alias'],
                         'account_type': r['account_type']} for r in c.fetchall()]
            logger.info(
                'Flex refresh satisfied user=%s trigger=%s source=database '
                'report_date=%s expected_date=%s',
                user_id, trigger, latest_stored, expected,
            )
            return latest_stored, False, None, accounts
        last_attempt = user['last_fetch_at'] or 0
        consecutive_failures = storage.count_consecutive_failures(conn, user_id)
    finally:
        return_db(conn)

    # Cache work can open its own DB transaction, so release the lookup
    # connection first. This also keeps the scheduler's connection usage
    # bounded when several users refresh concurrently.
    cached_result = _recover_cached_report(user_id, expected, trigger=trigger)
    if cached_result:
        return cached_result

    if not force:
        if consecutive_failures >= config['fetch_max_failures']:
            logger.warning(
                'Automatic Flex refresh skipped user=%s trigger=%s '
                'reason=retry_exhausted failures=%s max_backoff_seconds=%s',
                user_id, trigger, consecutive_failures,
                _retry_backoff_seconds(consecutive_failures),
            )
            return latest_stored, False, None, None

        backoff_seconds = _retry_backoff_seconds(consecutive_failures)
        elapsed = time.time() - last_attempt
        if elapsed < backoff_seconds:
            remaining = int(backoff_seconds - elapsed)
            logger.info(
                'Automatic Flex refresh skipped user=%s trigger=%s '
                'reason=backoff failures=%s backoff_seconds=%s '
                'retry_after_seconds=%s',
                user_id, trigger, consecutive_failures,
                backoff_seconds, remaining,
            )
            return latest_stored, False, None, None
    elif consecutive_failures:
        logger.info(
            'Manual Flex refresh bypassing retry backoff user=%s '
            'trigger=%s failures=%s',
            user_id, trigger, consecutive_failures,
        )

    conn = get_db()
    try:
        storage.set_user_fetch_at(conn, user_id, time.time())
    finally:
        return_db(conn)

    t0 = time.time()
    local_path = _cache_path(user_id)
    logger.info(
        'Calling IBKR Flex API user=%s trigger=%s expected_date=%s '
        'previous_failures=%s',
        user_id, trigger, expected, consecutive_failures,
    )

    try:
        xml_text = flex_client.get_flex_xml(
            flex_token, query_id,
            max_wait=config['flex_max_wait'],
            save_path=local_path,
        )
    except flex_client.FlexClientError as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        error_code = f'FLEX_{e.error_code}' if e.error_code else 'FLEX_TIMEOUT'
        _safe_log_error(
            user_id, error_code, str(e), expected, elapsed_ms,
            needs_attention=e.needs_attention,
            trigger=trigger, source='ibkr',
        )
        return None, False, f'IBKR fetch failed: {e}', None
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        error_code = 'LOCAL_CACHE_WRITE' if isinstance(e, OSError) else 'FLEX_UNEXPECTED'
        _safe_log_error(
            user_id, error_code, str(e), expected, elapsed_ms,
            trigger=trigger,
            source='local' if isinstance(e, OSError) else 'ibkr',
        )
        label = 'Local cache write failed' if isinstance(e, OSError) else 'IBKR fetch failed'
        return None, False, f'{label}: {e}', None

    logger.info(
        'IBKR Flex XML received user=%s trigger=%s expected_date=%s '
        'duration_ms=%s local_cache=%s',
        user_id, trigger, expected, int((time.time() - t0) * 1000), local_path,
    )

    try:
        data = flex_parser.parse_flex_xml(xml_text)
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        _safe_log_error(
            user_id, 'FLEX_PARSE', str(e), expected, elapsed_ms,
            trigger=trigger, source='ibkr',
        )
        return None, False, f'Parse failed: {e}', None

    report_date = data['date']
    accounts = _accounts_from_data(data)

    # The Flex client has already persisted the XML locally. Commit portfolio
    # data first, then archive canonically without extending request latency.
    err = _store_parsed_data(
        user_id, data, report_date, source='ibkr', trigger=trigger,
        duration_ms=int((time.time() - t0) * 1000),
    )
    if err:
        return None, False, err, accounts

    _archive_xml_in_background(
        user_id, report_date, xml_text, trigger=trigger
    )

    return report_date, True, None, accounts


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
def scheduled_refresh():
    """Hourly tick: refresh all eligible users concurrently."""
    conn = None
    try:
        conn = get_db()
        users = storage.get_active_users_with_credentials(conn)
    except Exception:
        logger.exception('Unable to load users for scheduled Flex refresh')
        return
    finally:
        if conn is not None:
            return_db(conn)

    if not users:
        logger.info('Scheduled Flex refresh found no eligible users')
        return

    logger.info('Scheduled Flex refresh started eligible_users=%s', len(users))

    from concurrent.futures import ThreadPoolExecutor, as_completed
    max_workers = config.get('scheduler_max_workers', 8)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                fetch_and_store, u['user_id'], trigger='automatic'
            ): u['user_id']
                   for u in users}
        for future in as_completed(futures):
            user_id = futures[future]
            try:
                report_date, is_new, error, _accounts = future.result()
                logger.info(
                    'Scheduled Flex refresh finished user=%s report_date=%s '
                    'is_new=%s error=%s',
                    user_id, report_date, is_new, bool(error),
                )
            except Exception:
                logger.exception('Scheduled refresh crashed for user %s', user_id)


def setup_scheduler():
    """Hourly self-check with concurrent per-user refresh."""
    if not config.get('scheduler_enabled', True):
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            scheduled_refresh, 'interval', hours=1,
            next_run_time=datetime.now() + timedelta(seconds=15),
            id='hourly_refresh',
        )
        scheduler.start()
    except ImportError:
        logger.warning('APScheduler is unavailable; hourly refresh is disabled')


# ---------------------------------------------------------------------------
# Portfolio builders
# ---------------------------------------------------------------------------
def account_summary(cursor, user_id, account_id):
    """NAV components / P&L totals for one account, or all merged."""
    cols = ('net_liquidation', 'cash_balance', 'stock_value', 'options_value',
            'dividend_accruals', 'interest_accruals',
            'previous_net_liquidation', 'day_pnl')
    select = ', '.join(f'SUM({c}) AS {c}' for c in cols)
    if account_id == 'ALL':
        cursor.execute(f'SELECT {select} FROM accounts WHERE user_id = ?',
                       (user_id,))
    else:
        cursor.execute(f'''SELECT {select} FROM accounts
                       WHERE user_id = ? AND account_id = ?''',
                       (user_id, account_id))
    row = cursor.fetchone()
    return {
        c: round(row[c], 2) if row and row[c] is not None else 0
        for c in cols
    }


def get_account_info(cursor, user_id):
    """user_id → {account_id: profile row}"""
    cursor.execute('SELECT * FROM accounts WHERE user_id = ?', (user_id,))
    return {r['account_id']: dict(r) for r in cursor.fetchall()}


def build_holding(row):
    """Map a positions row to the API holding dict."""
    return {
        'conid': row['conid'],
        'ticker': row['ticker'],
        'full_name': row['full_name'],
        'asset_class': row['asset_class'],
        'side': row['side'],
        'quantity': row['quantity'],
        'market_value': row['market_value'],
        'mark_price': row['mark_price'],
        'cost_price': row['cost_price'],
        'cost_basis': row['cost_basis'],
        'unrealized_pnl': row['unrealized_pnl'],
        'day_pnl': row['day_pnl'],
        'prev_close_price': row['prev_close_price'],
        'prev_close_quantity': row['prev_close_quantity'],
        'xml_percent_of_nav': row['xml_percent_of_nav'],
        'multiplier': row['multiplier'],
        'strike': row['strike'],
        'expiry': row['expiry'],
        'put_call': row['put_call'],
        'underlying_symbol': row['underlying_symbol'],
        'listing_exchange': row['listing_exchange'],
        'currency': row['currency'],
        'account_id': row['account_id'],
    }


def build_daily_pnl_contribution(row, mark_price=None):
    """Map a stored named MTM row to its API representation."""
    return {
        'conid': row['conid'],
        'ticker': row['ticker'],
        'full_name': row['full_name'],
        'asset_class': row['asset_class'],
        'day_pnl': row['day_pnl'],
        'prev_close_price': row['prev_close_price'],
        'prev_close_quantity': row['prev_close_quantity'],
        'currency': row['currency'],
        'account_id': row['account_id'],
        'mark_price': mark_price,
    }


def cash_holding(amount, account_id):
    return {
        'conid': '', 'ticker': 'CASH', 'full_name': 'Cash', 'asset_class': 'CASH',
        'side': 'LONG' if amount > 0 else 'SHORT',
        'quantity': amount, 'market_value': amount,
        'mark_price': None, 'cost_price': None, 'cost_basis': None,
        'unrealized_pnl': 0, 'day_pnl': 0,
        'prev_close_price': None, 'prev_close_quantity': None,
        'xml_percent_of_nav': None,
        'multiplier': None, 'strike': None, 'expiry': '', 'put_call': '',
        'underlying_symbol': '', 'listing_exchange': '', 'currency': 'USD',
        'account_id': account_id,
    }


def cash_holdings_for_view(summary, account_info, account_id):
    """Return signed cash positions without cross-account gross netting."""
    if account_id == 'ALL':
        balances = (
            (aid, round(account.get('cash_balance') or 0, 2))
            for aid, account in account_info.items()
        )
    else:
        balances = ((account_id, round(summary['cash_balance'], 2)),)
    return [
        cash_holding(value, aid)
        for aid, value in balances
        if value != 0
    ]


def group_summary(holdings, field):
    sums = defaultdict(float)
    for h in holdings:
        sums[h[field] or 'Other'] += h['market_value']
    return [
        {'name': name, 'value': round(value, 2)}
        for name, value in sorted(sums.items(), key=lambda kv: kv[1], reverse=True)
    ]


def _securities_value_from_xml(summary, holdings):
    """Return securities value from stored XML components when complete.

    Stock, ETF and option portfolios are covered by the stored EquitySummary
    fields. For any other asset class, sum positions because its corresponding
    EquitySummary component is not stored.
    """
    supported = {'STOCK', 'ETF', 'OPTION'}
    securities = [h for h in holdings if h['asset_class'] != 'CASH']
    if securities and all(h['asset_class'] in supported for h in securities):
        return round(summary['stock_value'] + summary['options_value'], 2)
    return sum(h['market_value'] for h in securities)


def exposure_summary(holdings, net_liquidation):
    """Signed exposure totals, with short exposure reported as a magnitude."""
    long_value = round(sum(max(h['market_value'], 0) for h in holdings), 2)
    short_value = round(sum(abs(min(h['market_value'], 0)) for h in holdings), 2)
    gross_value = round(long_value + short_value, 2)
    net_value = round(long_value - short_value, 2)
    nav = abs(net_liquidation)
    return {
        'long': long_value,
        'short': short_value,
        'gross': gross_value,
        'net': net_value,
        'gross_to_nav': round(gross_value / nav, 4) if nav else None,
        'net_to_nav': round(net_value / nav, 4) if nav else None,
    }


# ---------------------------------------------------------------------------
# Auth Routes
# ---------------------------------------------------------------------------
@app.route('/auth/login')
def auth_login():
    """Redirect to Google OAuth consent screen."""
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state
    params = {
        'client_id': config['google_client_id'],
        'redirect_uri': f"{config['base_url']}/auth/callback",
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
    }
    url = GOOGLE_AUTH_URL + '?' + '&'.join(f'{k}={requests.utils.quote(v)}' for k, v in params.items())
    return redirect(url)


@app.route('/auth/callback')
def auth_callback():
    """Handle Google OAuth callback: exchange code, verify id_token, upsert user."""
    state = request.args.get('state', '')
    if not state or state != session.pop('oauth_state', None):
        return 'Invalid state parameter — possible CSRF attack.', 400

    code = request.args.get('code', '')
    if not code:
        return 'Missing authorization code.', 400

    # Exchange code for tokens
    try:
        resp = requests.post(GOOGLE_TOKEN_URL, data={
            'code': code,
            'client_id': config['google_client_id'],
            'client_secret': config['google_client_secret'],
            'redirect_uri': f"{config['base_url']}/auth/callback",
            'grant_type': 'authorization_code',
        }, timeout=15)
        resp.raise_for_status()
        token_data = resp.json()
    except Exception as e:
        return f'Token exchange failed: {e}', 500

    id_token_str = token_data.get('id_token')
    if not id_token_str:
        return 'No id_token in response.', 500

    # Verify id_token
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    try:
        id_info = id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            config['google_client_id'],
        )
    except Exception as e:
        return f'ID token verification failed: {e}', 400

    google_sub = id_info['sub']
    email = id_info.get('email', '')
    name = id_info.get('name', email)

    conn = get_db()
    try:
        user = storage.get_user_by_google_sub(conn, google_sub)

        if user:
            storage.update_user_login(conn, user['user_id'], name)
            user_id = user['user_id']
        else:
            user_id = str(uuid.uuid4())
            storage.create_user(conn, user_id, email, name, google_sub)

        # Create server-side session
        session_id = str(uuid.uuid4())
        storage.create_session(conn, session_id, user_id,
                               ip_address=request.remote_addr,
                               user_agent=request.headers.get('User-Agent', ''))
    finally:
        return_db(conn)

    # Set signed cookie
    session['user_id'] = user_id
    session['session_id'] = session_id
    session.permanent = True

    return redirect('/')


@app.route('/auth/me')
def auth_me():
    """Return current user profile (or 401 if not authenticated)."""
    user_id = getattr(g, 'user_id', None)
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401
    conn = get_db_g()
    user = storage.get_user_by_id(conn, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    flex_token_masked = ''
    if user['flex_token_enc']:
        try:
            flex_token = storage.decrypt_flex_token(config, user['flex_token_enc'])
            if len(flex_token) > 8:
                flex_token_masked = (
                    f'{flex_token[:4]}'
                    f'{"*" * (len(flex_token) - 8)}'
                    f'{flex_token[-4:]}'
                )
            else:
                flex_token_masked = '*' * len(flex_token)
        except Exception:
            app.logger.warning(
                'Unable to create Flex token hint for user %s', user_id
            )

    return jsonify({
        'user_id': user['user_id'],
        'email': user['email'],
        'name': user['name'],
        'flex_query_id': user['flex_query_id'],
        'flex_token_masked': flex_token_masked,
        'has_flex_query': bool(user['flex_token_enc'] and user['flex_query_id']),
        'flex_status': user['flex_status'],
        'is_admin': bool(user['is_admin']),
        'created_at': user['created_at'],
        'last_login': user['last_login'],
    })


@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    """Clear session server-side and client-side."""
    sid = getattr(g, 'session_id', None) or session.get('session_id')
    if sid:
        conn = get_db_g()
        storage.delete_session(conn, sid)
    session.clear()
    return jsonify({'status': 'ok'})


# ---------------------------------------------------------------------------
# Setup Routes
# ---------------------------------------------------------------------------
@app.route('/api/setup/test-flex', methods=['POST'])
@login_required
def setup_test_flex():
    """Save and test Flex credentials through the synchronous fetch pipeline."""
    body = request.get_json(silent=True) or {}
    flex_token = (body.get('token') or '').strip()
    flex_query_id = (body.get('query_id') or '').strip()

    if not flex_token or not flex_query_id:
        return jsonify({'error': 'Token and Query ID are required.'}), 400

    # Save credentials first so fetch_and_store can read them
    conn = get_db_g()
    storage.set_user_flex_credentials(conn, config, g.user_id, flex_token, flex_query_id)

    # A credential test is an explicit user action, so bypass scheduler backoff.
    report_date, is_new, error, accounts = fetch_and_store(
        g.user_id, force=True, trigger='credential_test'
    )

    if error:
        return jsonify({'error': error}), 502

    return jsonify({
        'status': 'ok',
        'accounts': accounts or [],
        'report_date': report_date,
    })


@app.route('/api/setup/configure', methods=['POST'])
@login_required
def setup_configure():
    """Save Flex credentials. Data should already exist from test-flex."""
    body = request.get_json(silent=True) or {}
    flex_token = (body.get('token') or '').strip()
    flex_query_id = (body.get('query_id') or '').strip()

    if not flex_token or not flex_query_id:
        return jsonify({'error': 'Token and Query ID are required.'}), 400

    conn = get_db_g()
    storage.set_user_flex_credentials(conn, config, g.user_id, flex_token, flex_query_id)

    # Recover through DB → S3 → local cache; test-flex already called IBKR.
    report_date, is_new, error = refresh_user_data(g.user_id)

    user = storage.get_user_by_id(conn, g.user_id)

    if error:
        return jsonify({
            'status': 'error',
            'flex_status': user['flex_status'],
            'has_flex_query': True,
            'fetch_error': error,
        }), 502

    return jsonify({
        'status': 'ok',
        'flex_status': user['flex_status'],
        'has_flex_query': True,
        'report_date': report_date,
    })


@app.route('/api/setup/status')
@login_required
def setup_status():
    """Return Flex configuration status for the current user."""
    conn = get_db_g()
    user = storage.get_user_by_id(conn, g.user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({
        'flex_status': user['flex_status'],
        'flex_query_id': user['flex_query_id'],
        'has_flex_query': bool(user['flex_token_enc'] and user['flex_query_id']),
    })


# ---------------------------------------------------------------------------
# API Routes (all require login)
# ---------------------------------------------------------------------------
@app.route('/')
def serve_index():
    # SPA handles auth client-side
    if not os.path.exists(os.path.join(DIST_DIR, 'index.html')):
        return (
            'Frontend not built. Run: cd frontend && npm install && npm run build',
            503,
        )
    return send_from_directory(DIST_DIR, 'index.html')


@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(os.path.join(DIST_DIR, 'assets'), filename)


@app.route('/api/accounts')
@login_required
def get_accounts():
    user_id = g.user_id
    conn = get_db_g()
    c = conn.cursor()
    c.execute('''SELECT account_id, net_liquidation, day_pnl
                 FROM accounts WHERE user_id = ?
                 ORDER BY account_id''', (user_id,))
    rows = c.fetchall()
    info = get_account_info(c, user_id)
    user = storage.get_user_by_id(conn, user_id)
    refresh_date = user['last_refresh'] if user else ''

    accounts = []
    for r in rows:
        i = info.get(r['account_id'], {})
        accounts.append({
            'account_id': r['account_id'],
            'net_liquidation': r['net_liquidation'],
            'date': refresh_date,
            'day_pnl': r['day_pnl'],
            'alias': i.get('alias', ''),
            'account_type': i.get('account_type', 'MARGIN'),
            'syep': i.get('syep', ''),
            'drip': i.get('drip', ''),
            'tax_lot_method': i.get('tax_lot_method', ''),
            'date_opened': i.get('date_opened', ''),
        })
    return jsonify({'accounts': accounts})


@app.route('/api/portfolio')
@login_required
def get_portfolio():
    user_id = g.user_id
    account_id = request.args.get('account_id', 'ALL')
    conn = get_db_g()
    c = conn.cursor()

    c.execute('SELECT MAX(date) AS max_date FROM positions WHERE user_id = ?',
              (user_id,))
    latest_date = c.fetchone()['max_date']
    if not latest_date:
        # Reports created before CASH became a first-class position may have
        # no position rows at all for cash-only users. Their report date is
        # still available on the user record.
        user = storage.get_user_by_id(conn, user_id)
        latest_date = user['last_refresh'] if user else None
        if not latest_date:
            return jsonify({'error': 'No data'}), 404

    if account_id == 'ALL':
        c.execute('''SELECT * FROM positions
                     WHERE user_id = ? AND date = ?''', (user_id, latest_date))
    else:
        c.execute('''SELECT * FROM positions
                     WHERE user_id = ? AND date = ? AND account_id = ?''',
                  (user_id, latest_date, account_id))

    rows = c.fetchall()
    summary = account_summary(c, user_id, account_id)
    info = get_account_info(c, user_id)
    if account_id != 'ALL' and account_id not in info:
        return jsonify({'error': 'Account not found'}), 404
    account_ids = list(info) if account_id == 'ALL' else [account_id]

    # New reports persist CASH as a position. Strip it before calculating the
    # securities subtotal, then append one account-filtered aggregate below.
    # The fallback keeps reports stored before this change fully compatible.
    holdings = [build_holding(r) for r in rows]
    securities_value = _securities_value_from_xml(summary, holdings)
    holdings = [h for h in holdings if h['ticker'] != 'CASH']

    # Keep the dashboard available during a rolling deploy if the release
    # task has not created the new table yet. PostgreSQL requires a savepoint
    # here so an undefined-table error does not poison the request transaction.
    c.execute('SAVEPOINT daily_pnl_contributions_lookup')
    try:
        if account_id == 'ALL':
            c.execute('''SELECT * FROM daily_pnl_contributions
                         WHERE user_id = ? AND date = ? AND day_pnl <> 0''',
                      (user_id, latest_date))
        else:
            c.execute('''SELECT * FROM daily_pnl_contributions
                         WHERE user_id = ? AND date = ? AND account_id = ?
                           AND day_pnl <> 0''',
                      (user_id, latest_date, account_id))
        contribution_rows = c.fetchall()
    except Exception as exc:
        c.execute('ROLLBACK TO SAVEPOINT daily_pnl_contributions_lookup')
        sqlstate = (
            getattr(exc, 'pgcode', None) or getattr(exc, 'sqlstate', None)
        )
        if sqlstate != '42P01':
            raise
        logger.warning(
            'daily_pnl_contributions table is not installed; using holdings fallback'
        )
        contribution_rows = []
    finally:
        c.execute('RELEASE SAVEPOINT daily_pnl_contributions_lookup')

    mark_prices = {
        (h['account_id'], h['conid']): h['mark_price']
        for h in holdings if h['conid']
    }
    daily_pnl_contributions = [
        build_daily_pnl_contribution(
            row, mark_prices.get((row['account_id'], row['conid']))
        )
        for row in contribution_rows
    ]

    # Reports stored before this table was introduced retain the previous
    # position-based view until their XML is ingested again.
    if not daily_pnl_contributions:
        daily_pnl_contributions = [
            {
                'conid': h['conid'], 'ticker': h['ticker'],
                'full_name': h['full_name'], 'asset_class': h['asset_class'],
                'day_pnl': h['day_pnl'],
                'prev_close_price': h['prev_close_price'],
                'prev_close_quantity': h['prev_close_quantity'],
                'currency': h['currency'], 'account_id': h['account_id'],
                'mark_price': h['mark_price'],
            }
            for h in holdings if h['ticker'] != 'CASH' and h['day_pnl'] != 0
        ]

    # Keep account cash balances separate in the consolidated view. Netting a
    # positive balance in one account against margin financing in another
    # would understate both long/short books and therefore gross exposure.
    holdings.extend(cash_holdings_for_view(summary, info, account_id))
    holdings.sort(key=lambda h: abs(h['market_value']), reverse=True)
    exposures = exposure_summary(holdings, summary['net_liquidation'])

    return jsonify({
        'date': latest_date,
        'account_id': account_id,
        'accounts': account_ids,
        'aliases': {aid: info.get(aid, {}).get('alias', '') for aid in account_ids},
        'holdings': holdings,
        'daily_pnl_contributions': daily_pnl_contributions,
        'summary': {
            'total_value': round(securities_value, 2),
            'net_liquidation': summary['net_liquidation'],
            'total_cash': summary['cash_balance'],
            'previous_net_liquidation': summary['previous_net_liquidation'],
            'total_day_pnl': summary['day_pnl'],
        },
        'exposures': exposures,
        'equity': {
            'stock': summary['stock_value'],
            'options': summary['options_value'],
            'cash': summary['cash_balance'],
            'dividend_accruals': summary['dividend_accruals'],
            'interest_accruals': summary['interest_accruals'],
            'total': summary['net_liquidation'],
        },
        'asset_class_summary': group_summary(holdings, 'asset_class'),
        'ticker_summary': [
            {
                'name': h['ticker'],
                'value': h['market_value'],
                'full_name': h['full_name'],
                'day_pnl': h['day_pnl'],
            }
            for h in holdings
        ],
    })


@app.route('/api/targets', methods=['GET', 'POST'])
@login_required
def targets():
    user_id = g.user_id
    conn = get_db_g()

    if request.method == 'POST':
        body = request.get_json(silent=True) or {}
        account_id = body.get('account_id', 'ALL')
        raw = body.get('targets', {})
        clean = {}
        for k, v in (raw.items() if isinstance(raw, dict) else []):
            try:
                pct = float(v)
            except (TypeError, ValueError):
                continue
            if pct >= 0:
                clean[str(k)] = round(pct, 4)
        storage.set_targets(conn, user_id, account_id, clean)
        return jsonify({'account_id': account_id, 'targets': clean})

    account_id = request.args.get('account_id', 'ALL')
    saved = storage.get_targets(conn, user_id, account_id)
    return jsonify({'account_id': account_id, 'targets': saved})


@app.route('/api/trigger-refresh', methods=['POST'])
@login_required
def trigger_refresh():
    user_id = g.user_id
    conn = get_db_g()
    user = storage.get_user_by_id(conn, user_id)

    last_ts = user['last_manual_at'] or 0 if user else 0
    now_ts = time.time()

    cooldown = config['refresh_cooldown']
    elapsed = now_ts - last_ts
    if elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        logger.info(
            'Manual Flex refresh rate limited user=%s retry_after_seconds=%s',
            user_id, remaining,
        )
        return jsonify({
            'error': 'Rate limited',
            'retry_after_seconds': remaining,
            'message': f'Please wait {remaining}s before refreshing again'
        }), 429

    storage.set_user_manual_at(conn, user_id, now_ts)
    job_id = storage.create_refresh_job(conn, user_id)
    logger.info(
        'Manual Flex refresh accepted user=%s job_id=%s', user_id, job_id
    )

    worker = threading.Thread(
        target=_run_manual_refresh_job,
        args=(user_id, job_id),
        name=f'manual-refresh-{user_id}',
        daemon=True,
    )
    try:
        worker.start()
    except Exception as e:
        storage.update_refresh_job(
            conn, user_id, job_id, 'refresh_error', str(e)
        )
        return jsonify({'error': f'Unable to start refresh: {e}'}), 500

    return jsonify({
        'status': 'accepted',
        'job_id': job_id,
        'message': 'Refresh started',
    }), 202


def _run_manual_refresh_job(user_id, job_id):
    """Execute one manual refresh outside the request lifecycle."""
    conn = None
    try:
        conn = get_db()
        storage.update_refresh_job(
            conn, user_id, job_id, 'refresh_running',
            'Checking database and report caches',
        )
    finally:
        if conn is not None:
            return_db(conn)

    try:
        new_date, is_new, error, _accounts = fetch_and_store(
            user_id, force=True, trigger='manual'
        )
        if error:
            status = 'refresh_error'
            message = error
        elif is_new:
            status = 'refresh_success'
            message = f'New report stored: {new_date}'
        elif new_date:
            status = 'refresh_success'
            message = f'Already up to date — latest report is {new_date}'
        else:
            status = 'refresh_success'
            message = 'No report available yet'
    except Exception as e:
        logger.exception(
            'Manual refresh job crashed user=%s job_id=%s', user_id, job_id
        )
        status = 'refresh_error'
        message = f'Refresh failed unexpectedly: {e}'
        new_date = None

    conn = None
    try:
        conn = get_db()
        storage.update_refresh_job(
            conn, user_id, job_id, status, message, new_date
        )
    finally:
        if conn is not None:
            return_db(conn)


@app.route('/api/refresh-status/<int:job_id>')
@login_required
def refresh_job_status(job_id):
    conn = get_db_g()
    job = storage.get_refresh_job(conn, g.user_id, job_id)
    if not job:
        return jsonify({'error': 'Refresh job not found'}), 404

    status = job['status']
    if status in ('refresh_pending', 'refresh_running'):
        return jsonify({
            'status': 'running',
            'message': job['error_detail'] or 'Refresh is running',
        })
    if status == 'refresh_success':
        return jsonify({
            'status': 'success',
            'date': job['report_date'],
            'message': job['error_detail'] or 'Refresh completed',
        })
    if status == 'refresh_error':
        return jsonify({
            'status': 'error',
            'message': job['error_detail'] or 'Refresh failed',
            'retry_after_seconds': config['refresh_cooldown'],
        })
    return jsonify({'error': 'Invalid refresh job state'}), 500


@app.route('/api/status')
@login_required
def get_status():
    user_id = g.user_id
    conn = get_db_g()
    user = storage.get_user_by_id(conn, user_id)

    last_refresh = user['last_refresh'] if user else 'Never'
    last_ts = user['last_manual_at'] if user else 0
    if last_ts is None:
        last_ts = 0

    now_ts = time.time()
    cooldown_remaining = max(0, int(config['refresh_cooldown'] - (now_ts - last_ts)))

    c = conn.cursor()
    c.execute('''SELECT status, error_code, error_detail, created_at
                 FROM fetch_log WHERE user_id = ?
                   AND status IN ('success', 'warning', 'error')
                 ORDER BY id DESC LIMIT 1''', (user_id,))
    latest_attempt = c.fetchone()

    return jsonify({
        'last_refresh': last_refresh or 'Never',
        'refresh_cooldown_remaining': cooldown_remaining,
        'flex_status': user['flex_status'] if user else 'unknown',
        'last_attempt_status': latest_attempt['status'] if latest_attempt else None,
        'last_error_code': latest_attempt['error_code'] if latest_attempt else None,
        'last_error_detail': latest_attempt['error_detail'] if latest_attempt else None,
        'last_attempt_at': latest_attempt['created_at'] if latest_attempt else None,
    })


# ---------------------------------------------------------------------------
# Admin Routes
# ---------------------------------------------------------------------------
@app.route('/api/admin/users')
@admin_required
def admin_list_users():
    conn = get_db_g()
    c = conn.cursor()
    c.execute('''SELECT user_id, email, name, flex_status,
                 is_active, is_admin, created_at, last_login
                 FROM users ORDER BY created_at DESC''')
    users = []
    for row in c.fetchall():
        users.append({
            'user_id': row['user_id'],
            'email': row['email'],
            'name': row['name'],
            'flex_status': row['flex_status'],
            'is_active': bool(row['is_active']),
            'is_admin': bool(row['is_admin']),
            'created_at': row['created_at'],
            'last_login': row['last_login'],
        })
    return jsonify({'users': users})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
# Promote configured existing users at process startup.
admin_emails = config.get('admin_emails', [])
if admin_emails:
    conn = get_db()
    c = conn.cursor()
    for email in admin_emails:
        c.execute('UPDATE users SET is_admin = 1 WHERE email = ?', (email,))
    conn.commit()
    return_db(conn)

setup_scheduler()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', config['port']))
    app.run(debug=bool(config['debug']), host='0.0.0.0', port=port)
