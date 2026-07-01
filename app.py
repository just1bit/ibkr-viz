"""IBKR Portfolio Viz — multi-tenant Flask backend.

Google OAuth, per-user encrypted IBKR Flex credentials, user-scoped data.
"""

import os
import time
import json
import uuid
import secrets
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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

        # Database
        'db_type': 'sqlite',
        'db_path': os.path.join(BASE_DIR, 'ibkr_portfolio.db'),
        'postgres_url': '',

        # S3
        's3_bucket': '',
        's3_endpoint': '',
        's3_region': 'us-east-1',
        's3_access_key': '',
        's3_secret_key': '',
        's3_prefix': 'flex_raw/',

        # Scheduler
        'market_timezone': 'America/New_York',
        'report_ready_hour': 1,
        'fetch_retry_backoff': 3600,
        'refresh_cooldown': 600,
        'scheduler_max_workers': 8,

        # Admin
        'admin_emails': [],

        # Server
        'port': 5123,
        'debug': True,
    }
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            user_cfg = yaml.safe_load(f) or {}
        defaults.update(user_cfg)
    return defaults


config = load_config()
app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=config['secret_key'],
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_SECURE=config['base_url'].startswith('https'),
)
s3_store = storage.S3Store(config)

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
    """Validate the server-side session record on every request.

    Flask's signed cookie carries {user_id, session_id}. We cross-check
    against the sessions table so we can invalidate sessions server-side
    (logout, admin force-logout, expiry).
    """
    # Allow auth routes and static assets through without session check
    if request.path.startswith('/auth/') or request.path.startswith('/assets/'):
        return

    sid = session.get('session_id')
    uid = session.get('user_id')
    if sid and uid:
        conn = get_db()
        if storage.validate_session(conn, sid, uid):
            g.user_id = uid
            g.session_id = sid
            g._db_conn = conn  # reuse this conn in routes via get_db_g()
            return
        return_db(conn)
    # Invalid or missing → clear cookie
    session.clear()


@app.teardown_appcontext
def close_db_conn(exc):
    conn = getattr(g, '_db_conn', None)
    if conn is not None:
        return_db(conn)
        g._db_conn = None


def get_db_g():
    """Return the request-scoped DB connection (set by load_session)."""
    if hasattr(g, '_db_conn') and g._db_conn is not None:
        return g._db_conn
    return get_db()


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
    """Insert one parsed Flex report into the database (no commit).

    All rows are scoped to user_id. Writes current_state (upsert),
    daily_snapshot rows, and account_info (upsert).
    """
    c = conn.cursor()
    for acc in data['accounts']:
        aid = acc['account_id']

        c.execute('''INSERT INTO current_state
            (user_id, account_id, net_liquidation, cash_balance, stock_value,
             options_value, dividend_accruals, interest_accruals, day_pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, account_id) DO UPDATE SET
             net_liquidation=excluded.net_liquidation,
             cash_balance=excluded.cash_balance,
             stock_value=excluded.stock_value,
             options_value=excluded.options_value,
             dividend_accruals=excluded.dividend_accruals,
             interest_accruals=excluded.interest_accruals,
             day_pnl=excluded.day_pnl''',
            (user_id, aid, acc['net_liquidation'], acc['cash_balance'],
             acc['stock_value'], acc['options_value'],
             acc['dividend_accruals'], acc['interest_accruals'],
             acc['day_pnl']))

        c.execute('DELETE FROM account_info WHERE user_id = ? AND account_id = ?',
                  (user_id, aid))
        c.execute('''INSERT INTO account_info
            (user_id, account_id, alias, account_type, syep, drip,
             tax_lot_method, date_opened)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (user_id, aid, acc['alias'], acc['account_type'], acc['syep'],
             acc['drip'], acc['tax_lot_method'], acc['date_opened']))

        for h in acc['holdings']:
            c.execute('''INSERT INTO daily_snapshot
                (user_id, date, account_id, conid, ticker, full_name,
                 asset_class, side, quantity, market_value, mark_price,
                 cost_price, cost_basis, unrealized_pnl, day_pnl,
                 prev_close_price, prev_close_quantity, multiplier,
                 strike, expiry, put_call, underlying_symbol,
                 listing_exchange, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (user_id, report_date, aid, h['conid'], h['ticker'],
                 h['full_name'], h['asset_class'], h['side'],
                 h['quantity'], h['market_value'], h['mark_price'],
                 h['cost_price'], h['cost_basis'], h['unrealized_pnl'],
                 h['day_pnl'], h['prev_close_price'],
                 h['prev_close_quantity'], h['multiplier'],
                 h['strike'], h['expiry'], h['put_call'],
                 h['underlying_symbol'], h['listing_exchange'],
                 h['currency']))


# ---------------------------------------------------------------------------
# Per-user data refresh
# ---------------------------------------------------------------------------
def _safe_log_error(user_id, error_code, error_detail,
                    report_date=None, duration_ms=None):
    """Log a fetch error. Never throws — failures here are silently dropped
    so the original caller's error is not cascaded."""
    conn = None
    try:
        conn = get_db()
        storage.log_fetch_error(conn, user_id, error_code, error_detail,
                                report_date, duration_ms)
        failures = storage.count_consecutive_failures(conn, user_id)
        if error_code in ('FLEX_AUTH', 'FLEX_PARSE'):
            storage.set_user_flex_status(conn, user_id, 'needs_attention')
        elif failures >= 6:
            storage.set_user_flex_status(conn, user_id, 'needs_attention')
        elif failures >= 3:
            storage.set_user_flex_status(conn, user_id, 'error')
        conn.commit()
    except Exception:
        pass
    finally:
        if conn is not None:
            return_db(conn)


def _cleanup_temp(path):
    """Remove a temp file. Never throws."""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def refresh_user_data(user_id):
    """Fetch IBKR Flex data for one user. Returns (report_date, is_new, error).
    DB connection is released before the network call and re-acquired after."""
    # ---- Phase 1: DB read --------------------------------------------------
    conn = get_db()
    try:
        user = storage.get_user_by_id(conn, user_id)
        if not user or not user['flex_token_enc'] or not user['flex_query_id']:
            return None, False, 'Flex credentials not configured'

        try:
            flex_token = storage.decrypt_flex_token(config, user['flex_token_enc'])
        except Exception as e:
            return None, False, f'Token decryption failed: {e}'

        query_id = user['flex_query_id']

        # Determine expected report date for this user
        tz = ZoneInfo(user['market_timezone']) if user.get('market_timezone') else MARKET_TZ
        now_mkt = datetime.now(tz)
        expected = _expected_report_date(now_mkt)

        c = conn.cursor()
        c.execute('SELECT MAX(date) AS latest FROM daily_snapshot WHERE user_id = ?',
                  (user_id,))
        row = c.fetchone()
        latest_stored = row['latest'] if row else None

        if latest_stored and latest_stored >= expected:
            return latest_stored, False, None

        try:
            last_attempt = float(
                storage.get_config_val(conn, user_id, 'last_fetch_attempt', '0') or '0')
        except (TypeError, ValueError):
            last_attempt = 0

        if time.time() - last_attempt < config['fetch_retry_backoff']:
            return latest_stored, False, None

        storage.set_config_val(conn, user_id, 'last_fetch_attempt', str(time.time()))
    finally:
        return_db(conn)

    # ---- Phase 2: Network (no DB connection held) --------------------------
    today_str = now_mkt.strftime('%Y-%m-%d')
    local_path = os.path.join(BASE_DIR, f'flex_raw_{user_id}_{today_str}.xml')
    t0 = time.time()

    try:
        xml_text = flex_client.get_flex_xml(
            flex_token, query_id,
            max_wait=config['flex_max_wait'],
            save_path=local_path,
        )
    except flex_client.FlexClientError as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        _safe_log_error(user_id,
                        'FLEX_AUTH' if 'Error' in str(e) else 'FLEX_TIMEOUT',
                        str(e), expected, elapsed_ms)
        _cleanup_temp(local_path)
        return None, False, f'IBKR fetch failed: {e}'
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        _safe_log_error(user_id, 'FLEX_TIMEOUT', str(e), expected, elapsed_ms)
        _cleanup_temp(local_path)
        return None, False, f'IBKR fetch failed: {e}'

    try:
        data = flex_parser.parse_flex_xml(xml_text)
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        _safe_log_error(user_id, 'FLEX_PARSE', str(e), expected, elapsed_ms)
        _cleanup_temp(local_path)
        return None, False, f'Parse failed: {e} — raw XML at {local_path}'

    report_date = data['date']

    s3_store.save_raw_xml(report_date, xml_text)
    if not s3_store.verify_raw_xml(report_date):
        elapsed_ms = int((time.time() - t0) * 1000)
        _safe_log_error(user_id, 'S3_UPLOAD', 'S3 verification failed',
                        report_date, elapsed_ms)
        _cleanup_temp(local_path)
        return None, False, f'S3 upload verification failed — raw XML at {local_path}'

    # ---- Phase 3: DB write -------------------------------------------------
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''SELECT COUNT(*) AS cnt FROM daily_snapshot
                     WHERE user_id = ? AND date = ?''', (user_id, report_date))
        already_stored = c.fetchone()['cnt'] > 0

        if not already_stored:
            store_report(conn, user_id, data, report_date)

        storage.set_config_val(conn, user_id, 'last_refresh', report_date)
        storage.set_config_val(conn, user_id, 'last_fetch_attempt', str(time.time()))
        storage.set_user_flex_status(conn, user_id, 'healthy')

        elapsed_ms = int((time.time() - t0) * 1000)
        storage.log_fetch_success(conn, user_id, report_date, elapsed_ms)
        conn.commit()
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        _safe_log_error(user_id, 'DB_INSERT', str(e), report_date, elapsed_ms)
        _cleanup_temp(local_path)
        return None, False, f'Database insert failed: {e} — raw XML at {local_path}'
    finally:
        return_db(conn)

    # Success — clean up temp file
    _cleanup_temp(local_path)

    return report_date, (not already_stored), None


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
def scheduled_refresh():
    """Hourly tick: refresh all eligible users concurrently."""
    conn = get_db()
    users = storage.get_active_users_with_credentials(conn)
    return_db(conn)

    if not users:
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed
    max_workers = config.get('scheduler_max_workers', 8)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(refresh_user_data, u['user_id']): u['user_id']
                   for u in users}
        for future in as_completed(futures):
            user_id = futures[future]
            try:
                future.result()
            except Exception:
                pass  # per-user errors already logged in refresh_user_data


def setup_scheduler():
    """Hourly self-check with concurrent per-user refresh."""
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
        pass  # APScheduler optional


# ---------------------------------------------------------------------------
# Portfolio builders
# ---------------------------------------------------------------------------
def account_summary(cursor, user_id, account_id):
    """NAV components / P&L totals for one account, or all merged."""
    cols = ('net_liquidation', 'cash_balance', 'stock_value', 'options_value',
            'dividend_accruals', 'interest_accruals', 'day_pnl')
    select = ', '.join(f'SUM({c}) AS {c}' for c in cols)
    if account_id == 'ALL':
        cursor.execute(f'SELECT {select} FROM current_state WHERE user_id = ?',
                       (user_id,))
    else:
        cursor.execute(f'''SELECT {select} FROM current_state
                           WHERE user_id = ? AND account_id = ?''',
                       (user_id, account_id))
    row = cursor.fetchone()
    return {c: round(row[c], 2) if row and row[c] is not None else 0 for c in cols}


def get_account_info(cursor, user_id):
    """user_id → {account_id: profile row}"""
    cursor.execute('SELECT * FROM account_info WHERE user_id = ?', (user_id,))
    return {r['account_id']: dict(r) for r in cursor.fetchall()}


def build_holding(row):
    """Map a daily_snapshot row to the API holding dict."""
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
        'multiplier': row['multiplier'],
        'strike': row['strike'],
        'expiry': row['expiry'],
        'put_call': row['put_call'],
        'underlying_symbol': row['underlying_symbol'],
        'listing_exchange': row['listing_exchange'],
        'currency': row['currency'],
        'account_id': row['account_id'],
    }


def cash_holding(amount, account_id):
    return {
        'conid': '', 'ticker': 'CASH', 'full_name': 'Cash', 'asset_class': 'CASH',
        'side': '', 'quantity': amount, 'market_value': amount,
        'mark_price': None, 'cost_price': None, 'cost_basis': None,
        'unrealized_pnl': 0, 'day_pnl': 0,
        'prev_close_price': None, 'prev_close_quantity': None,
        'multiplier': None, 'strike': None, 'expiry': '', 'put_call': '',
        'underlying_symbol': '', 'listing_exchange': '', 'currency': 'USD',
        'account_id': account_id,
    }


def group_summary(holdings, field):
    sums = defaultdict(float)
    for h in holdings:
        sums[h[field] or 'Other'] += h['market_value']
    return [
        {'name': name, 'value': round(value, 2)}
        for name, value in sorted(sums.items(), key=lambda kv: kv[1], reverse=True)
    ]


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
    # Validate state (CSRF)
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
    return jsonify({
        'user_id': user['user_id'],
        'email': user['email'],
        'name': user['name'],
        'flex_query_id': user['flex_query_id'],
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
    """Test Flex credentials without saving. Returns account list on success."""
    body = request.get_json(silent=True) or {}
    flex_token = (body.get('token') or '').strip()
    flex_query_id = (body.get('query_id') or '').strip()

    if not flex_token or not flex_query_id:
        return jsonify({'error': 'Token and Query ID are required.'}), 400

    try:
        xml_text = flex_client.get_flex_xml(
            flex_token, flex_query_id, max_wait=config['flex_max_wait'])
    except flex_client.FlexClientError as e:
        msg = str(e)
        if 'Error' in msg:
            if 'token' in msg.lower():
                return jsonify({'error': 'Token not recognized by IBKR. Copy it directly from your IBKR Flex Query page.'}), 400
            elif 'query' in msg.lower():
                return jsonify({'error': 'Query ID not found. Check the ID in your IBKR Flex Query configuration.'}), 400
            else:
                return jsonify({'error': f'IBKR error: {msg}'}), 400
        return jsonify({'error': f'IBKR Flex Web Service is temporarily unavailable. Please try again later. ({msg})'}), 502
    except Exception as e:
        return jsonify({'error': f'Cannot connect. Check your internet connection. ({e})'}), 502

    try:
        data = flex_parser.parse_flex_xml(xml_text)
    except Exception as e:
        return jsonify({
            'error': 'Your Flex Query may be missing required sections. '
                     'Ensure it includes: Open Positions, Equity Summary, MTM Performance.'
        }), 400

    accounts = [
        {'account_id': a['account_id'], 'alias': a['alias'], 'account_type': a['account_type']}
        for a in data['accounts']
    ]
    return jsonify({'status': 'ok', 'accounts': accounts, 'report_date': data['date']})


@app.route('/api/setup/configure', methods=['POST'])
@login_required
def setup_configure():
    """Save Flex credentials and trigger initial data fetch."""
    body = request.get_json(silent=True) or {}
    flex_token = (body.get('token') or '').strip()
    flex_query_id = (body.get('query_id') or '').strip()

    if not flex_token or not flex_query_id:
        return jsonify({'error': 'Token and Query ID are required.'}), 400

    conn = get_db_g()
    storage.set_user_flex_credentials(conn, config, g.user_id, flex_token, flex_query_id)

    # Trigger initial data fetch
    report_date, is_new, error = refresh_user_data(g.user_id)

    user = storage.get_user_by_id(conn, g.user_id)
    result = {
        'status': 'ok',
        'flex_status': user['flex_status'],
        'has_flex_query': True,
    }
    if report_date:
        result['report_date'] = report_date
    if error:
        result['fetch_error'] = error

    return jsonify(result)


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
                 FROM current_state WHERE user_id = ?
                 ORDER BY account_id''', (user_id,))
    rows = c.fetchall()
    info = get_account_info(c, user_id)

    refresh_date = storage.get_config_val(conn, user_id, 'last_refresh', '')

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

    c.execute('SELECT MAX(date) AS max_date FROM daily_snapshot WHERE user_id = ?',
              (user_id,))
    latest_date = c.fetchone()['max_date']
    if not latest_date:
        return jsonify({'error': 'No data'}), 404

    if account_id == 'ALL':
        c.execute('''SELECT * FROM daily_snapshot
                     WHERE user_id = ? AND date = ?''', (user_id, latest_date))
    else:
        c.execute('''SELECT * FROM daily_snapshot
                     WHERE user_id = ? AND date = ? AND account_id = ?''',
                  (user_id, latest_date, account_id))

    rows = c.fetchall()
    if not rows:
        return jsonify({'error': 'No holdings found'}), 404

    summary = account_summary(c, user_id, account_id)

    c.execute('''SELECT DISTINCT account_id FROM daily_snapshot
                 WHERE user_id = ? AND date = ?''', (user_id, latest_date))
    account_ids = [r['account_id'] for r in c.fetchall()]
    info = get_account_info(c, user_id)

    holdings = [build_holding(r) for r in rows]
    securities_value = sum(h['market_value'] for h in holdings)

    cash_value = round(max(summary['cash_balance'], 0), 2)
    if cash_value > 0:
        holdings.append(cash_holding(cash_value, account_id))
    holdings.sort(key=lambda h: h['market_value'], reverse=True)

    return jsonify({
        'date': latest_date,
        'account_id': account_id,
        'accounts': account_ids,
        'aliases': {aid: info.get(aid, {}).get('alias', '') for aid in account_ids},
        'holdings': holdings,
        'summary': {
            'total_value': round(securities_value, 2),
            'net_liquidation': summary['net_liquidation'],
            'total_cash': summary['cash_balance'],
            'total_day_pnl': summary['day_pnl'],
        },
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
        storage.set_config_val(conn, user_id, f'targets_{account_id}', json.dumps(clean))
        return jsonify({'account_id': account_id, 'targets': clean})

    account_id = request.args.get('account_id', 'ALL')
    raw = storage.get_config_val(conn, user_id, f'targets_{account_id}', '{}')
    try:
        saved = json.loads(raw)
    except Exception:
        saved = {}
    return jsonify({'account_id': account_id, 'targets': saved})


@app.route('/api/trigger-refresh')
@login_required
def trigger_refresh():
    user_id = g.user_id
    conn = get_db_g()

    last_manual = storage.get_config_val(conn, user_id, 'last_manual_refresh', '0')
    now_ts = time.time()
    try:
        last_ts = float(last_manual)
    except (ValueError, TypeError):
        last_ts = 0

    cooldown = config['refresh_cooldown']
    elapsed = now_ts - last_ts
    if elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        return jsonify({
            'error': 'Rate limited',
            'retry_after_seconds': remaining,
            'message': f'Please wait {remaining}s before refreshing again'
        }), 429

    storage.set_config_val(conn, user_id, 'last_manual_refresh', str(now_ts))

    new_date, is_new, error = refresh_user_data(user_id)
    if error:
        return jsonify({'error': error}), 500
    if is_new:
        message = f'New report stored: {new_date}'
    elif new_date:
        message = f'Already up to date — latest report is {new_date}'
    else:
        message = 'No report available yet'
    return jsonify({
        'status': 'ok',
        'date': new_date,
        'message': message
    })


@app.route('/api/status')
@login_required
def get_status():
    user_id = g.user_id
    conn = get_db_g()

    last_refresh = storage.get_config_val(conn, user_id, 'last_refresh', 'Never')
    last_manual = storage.get_config_val(conn, user_id, 'last_manual_refresh', '0')
    user = storage.get_user_by_id(conn, user_id)

    now_ts = time.time()
    try:
        last_ts = float(last_manual)
        cooldown_remaining = max(0, int(config['refresh_cooldown'] - (now_ts - last_ts)))
    except (ValueError, TypeError):
        cooldown_remaining = 0

    return jsonify({
        'last_refresh': last_refresh,
        'refresh_cooldown_remaining': cooldown_remaining,
        'flex_status': user['flex_status'] if user else 'unknown',
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
# Create tables if they don't exist (idempotent)
conn = get_db()
storage.init_db(conn)
return_db(conn)

# Check: admin emails → set is_admin flag on next login
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
