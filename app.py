"""IBKR Portfolio Viz — Flask backend.

Single-file Flask application. Storage is SQLite or PostgreSQL (storage.py);
an hourly APScheduler job self-checks for new IBKR reports (market-timezone
gated, see refresh_real_data). Runs in mock mode by default (no credentials).
"""

import os
import time
import json
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import yaml
from flask import Flask, request, jsonify, send_from_directory

import storage
import mock_data
import flex_client
import flex_parser

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, 'frontend', 'dist')

def load_config():
    cfg_path = os.path.join(BASE_DIR, 'config.local.yaml')
    # Defaults for every configurable knob — config.example.yaml documents them
    defaults = {
        'mock_mode': True,
        'flex_token': '',
        'flex_query_id': '',
        'flex_max_wait': 30,
        'db_type': 'sqlite',
        'db_path': os.path.join(BASE_DIR, 'ibkr_portfolio.db'),
        'postgres_url': '',
        'market_timezone': 'America/New_York',
        'report_ready_hour': 1,
        'refresh_cooldown': 600,
        'fetch_retry_backoff': 3600,
        's3_bucket': '',
        's3_endpoint': '',
        's3_region': 'us-east-1',
        's3_access_key': '',
        's3_secret_key': '',
        's3_prefix': 'flex_raw/',
        'port': 5123,
        'debug': True,
    }
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            user = yaml.safe_load(f) or {}
        defaults.update(user)
    return defaults

config = load_config()
app = Flask(__name__, static_folder=None)
s3_store = storage.S3Store(config)

# All report-cycle decisions are made in the market's timezone, so behavior
# is identical no matter where (or in how many places) the app is deployed.
MARKET_TZ = ZoneInfo(config['market_timezone'])

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    return storage.connect(config)

def init_db():
    conn = get_db()
    storage.init_db(conn)
    conn.close()

def _migrate_to_current_state():
    """One-shot migration: populate current_state from the latest nav_history
    rows, then drop the old nav_history and cash_report tables.

    Safe to call repeatedly — does nothing if current_state already has data
    or if the old tables don't exist."""
    conn = get_db()
    c = conn.cursor()

    # Already migrated?
    c.execute('SELECT COUNT(*) AS cnt FROM current_state')
    if c.fetchone()['cnt'] > 0:
        conn.close()
        return

    # Check if old tables exist
    try:
        c.execute('SELECT COUNT(*) AS cnt FROM nav_history')
    except Exception:
        conn.close()
        return  # Old tables already gone or never existed

    # Migrate latest per-account nav_history → current_state
    try:
        c.execute('''
            INSERT INTO current_state
                (account_id, net_liquidation, cash_balance, stock_value,
                 options_value, dividend_accruals, interest_accruals, day_pnl)
            SELECT n.account_id, n.net_liquidation, n.cash_balance,
                   n.stock_value, n.options_value, n.dividend_accruals,
                   n.interest_accruals, n.day_pnl
            FROM nav_history n
            WHERE n.date = (SELECT MAX(date) FROM nav_history
                            WHERE account_id = n.account_id)
        ''')
    except Exception:
        conn.rollback()
        conn.close()
        return  # Column mismatch or other schema issue — skip

    # Drop old tables
    try:
        c.execute('DROP TABLE IF EXISTS nav_history')
        c.execute('DROP TABLE IF EXISTS cash_report')
    except Exception:
        pass

    conn.commit()
    conn.close()

def ensure_data():
    """Seed mock data if DB is empty and mock_mode is on."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) AS cnt FROM config WHERE key = 'last_refresh'")
    count = c.fetchone()['cnt']
    conn.close()
    if count == 0 and config['mock_mode']:
        conn = get_db()
        mock_data.seed_database(conn)
        conn.close()

def get_config_val(key, default=None):
    conn = get_db()
    val = storage.get_config_val(conn, key, default)
    conn.close()
    return val

def set_config_val(key, value):
    conn = get_db()
    storage.set_config_val(conn, key, value)
    conn.close()

def _expected_report_date(now_mkt):
    """Newest report date IBKR should have published by `now_mkt`.

    `now_mkt` must be an aware datetime in MARKET_TZ; callers pass
    datetime.now(MARKET_TZ), so the result is independent of the server's
    own timezone. A statement for trading day T is generated around
    00:15-00:30 ET on T+1 (observed), so past report_ready_hour (default
    01:00 ET) we expect yesterday's report, before it only the day before
    yesterday's, skipping weekends. Market holidays are unknown here, so on
    holidays the expected date overshoots — the retry backoff in
    refresh_real_data bounds the extra IBKR calls that causes.
    """
    days_back = 1 if now_mkt.hour >= config['report_ready_hour'] else 2
    d = now_mkt.date() - timedelta(days=days_back)
    while d.weekday() >= 5:  # Sat/Sun → previous Friday
        d -= timedelta(days=1)
    return d.strftime('%Y-%m-%d')


def store_report(conn, data, report_date):
    """Insert one parsed Flex report into the database (no commit).

    Writes current_state (NAV components, upserted), daily_snapshot rows
    keyed by the report date, and upserts the per-account profile into
    account_info. Also used by the standalone re-ingest path, so it must not
    depend on request context.
    """
    c = conn.cursor()
    for acc in data['accounts']:
        aid = acc['account_id']

        c.execute('''INSERT INTO current_state
            (account_id, net_liquidation, cash_balance, stock_value,
             options_value, dividend_accruals, interest_accruals, day_pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
             net_liquidation=excluded.net_liquidation,
             cash_balance=excluded.cash_balance,
             stock_value=excluded.stock_value,
             options_value=excluded.options_value,
             dividend_accruals=excluded.dividend_accruals,
             interest_accruals=excluded.interest_accruals,
             day_pnl=excluded.day_pnl''',
            (aid, acc['net_liquidation'], acc['cash_balance'],
             acc['stock_value'], acc['options_value'],
             acc['dividend_accruals'], acc['interest_accruals'],
             acc['day_pnl']))

        c.execute('DELETE FROM account_info WHERE account_id = ?', (aid,))
        c.execute('''INSERT INTO account_info
            (account_id, alias, account_type, syep, drip, tax_lot_method,
             date_opened)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (aid, acc['alias'], acc['account_type'], acc['syep'], acc['drip'],
             acc['tax_lot_method'], acc['date_opened']))

        for h in acc['holdings']:
            c.execute('''INSERT INTO daily_snapshot
                (date, account_id, conid, ticker, full_name, asset_class,
                 side, quantity, market_value, mark_price,
                 cost_price, cost_basis, unrealized_pnl, day_pnl,
                 prev_close_price, prev_close_quantity, multiplier,
                 strike, expiry, put_call, underlying_symbol,
                 listing_exchange, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (report_date, aid, h['conid'], h['ticker'], h['full_name'],
                 h['asset_class'], h['side'], h['quantity'],
                 h['market_value'], h['mark_price'], h['cost_price'],
                 h['cost_basis'], h['unrealized_pnl'], h['day_pnl'],
                 h['prev_close_price'], h['prev_close_quantity'],
                 h['multiplier'], h['strike'], h['expiry'], h['put_call'],
                 h['underlying_symbol'], h['listing_exchange'],
                 h['currency']))


def refresh_real_data():
    """Fetch and store real IBKR Flex data, querying IBKR only when needed.

    IBKR rate-limits Flex requests, so one is sent only when a report newer
    than what the database holds should already be published (see
    _expected_report_date), and at most once per fetch_retry_backoff seconds
    while the expected report keeps failing to appear.

    The statement covers IBKR's last business day, which lags the fetch date
    by 1-2 days. All storage (S3 key, DB rows, last_refresh) is therefore
    keyed by the report date parsed from the XML (toDate) — NEVER the local
    fetch date.

    Pipeline (each step must succeed before the next):
      1. Fetch XML from IBKR → saved to LOCAL file immediately by flex_client
      2. Parse XML in memory → yields the report date
      3. Upload local file → S3 under the report date, verify it exists
      4. Insert parsed data into database under the report date
      5. Delete local file (only on full success)

    If any step fails, the local raw file is preserved so we never lose data
    that cost an IBKR rate-limited fetch.

    Returns:
        (report_date, is_new, error) — is_new is True when this call stored
        a report date not previously in the database.
    """
    token = config.get('flex_token', '')
    query_id = config.get('flex_query_id', '')
    if not token or not query_id:
        return None, False, 'Flex token or query ID not configured'

    now_mkt = datetime.now(MARKET_TZ)
    today = now_mkt.strftime('%Y-%m-%d')  # only used for the temp file name
    expected = _expected_report_date(now_mkt)

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT MAX(date) AS latest FROM daily_snapshot')
    row = c.fetchone()
    latest_stored = row['latest'] if row else None
    conn.close()

    # The newest publishable report is already stored — nothing to ask IBKR
    if latest_stored and latest_stored >= expected:
        return latest_stored, False, None

    # Expected report is missing: query IBKR, but back off between retries
    # so a late report or an unrecognized holiday can't cause hammering.
    try:
        last_attempt = float(get_config_val('last_fetch_attempt', '0') or 0)
    except (TypeError, ValueError):
        last_attempt = 0
    if time.time() - last_attempt < config['fetch_retry_backoff']:
        return latest_stored, False, None
    set_config_val('last_fetch_attempt', str(time.time()))

    local_path = os.path.join(BASE_DIR, f'flex_raw_{today}.xml')

    # --- Step 1: Fetch + save locally (save happens inside get_flex_xml) ---
    try:
        xml_text = flex_client.get_flex_xml(token, query_id,
                                            max_wait=config['flex_max_wait'],
                                            save_path=local_path)
    except Exception as e:
        return None, False, f'IBKR fetch failed: {e}'

    # --- Step 2: Parse (the report date comes from the statement itself) ---
    try:
        data = flex_parser.parse_flex_xml(xml_text)
    except Exception as e:
        return None, False, f'Parse failed: {e} — raw XML preserved at {local_path}'
    report_date = data['date']

    # --- Step 3: Upload to S3 + verify ---
    s3_store.save_raw_xml(report_date, xml_text)
    if not s3_store.verify_raw_xml(report_date):
        return None, False, f'S3 upload verification failed — raw XML preserved at {local_path}'

    # --- Step 4: Insert into database (skip if report date already stored) ---
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) AS cnt FROM daily_snapshot WHERE date = ?',
                  (report_date,))
        already_stored = c.fetchone()['cnt'] > 0

        if not already_stored:
            store_report(conn, data, report_date)

        set_config_val('last_refresh', report_date)
        conn.commit()
        conn.close()
    except Exception as e:
        return None, False, f'Database insert failed: {e} — raw XML preserved at {local_path}'

    # --- Step 5: Clean up local file on success ---
    if os.path.exists(local_path):
        os.remove(local_path)

    return report_date, (not already_stored), None

# ---------------------------------------------------------------------------
# Portfolio builders (colors are assigned by the frontend, not here)
# ---------------------------------------------------------------------------
def account_summary(cursor, account_id):
    """NAV components / P&L totals for one account, or all accounts merged.

    Reads from the current_state table (one row per account, upserted on
    each refresh). Always returns numeric values (missing rows default to 0)."""
    cols = ('net_liquidation', 'cash_balance', 'stock_value', 'options_value',
            'dividend_accruals', 'interest_accruals', 'day_pnl')
    select = ', '.join(f'SUM({c}) AS {c}' for c in cols)
    if account_id == 'ALL':
        cursor.execute(f'SELECT {select} FROM current_state')
    else:
        cursor.execute(f'''SELECT {select} FROM current_state
                           WHERE account_id = ?''', (account_id,))
    row = cursor.fetchone()
    return {c: round(row[c], 2) if row and row[c] is not None else 0 for c in cols}


def get_account_info(cursor):
    """account_id → profile row from account_info, as plain dicts."""
    cursor.execute('SELECT * FROM account_info')
    return {r['account_id']: dict(r) for r in cursor.fetchall()}


def build_holding(row):
    """Map a daily_snapshot row to the API holding dict.

    Every figure is the statement's own value — unrealized P&L comes from
    fifoPnlUnrealized and day P&L from the MTM summary, not local math."""
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
    """Cash represented as a holding so it joins the allocation breakdown."""
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
    """Sum holdings by a field (e.g. asset_class), sorted by value desc."""
    sums = defaultdict(float)
    for h in holdings:
        sums[h[field] or 'Other'] += h['market_value']
    return [
        {'name': name, 'value': round(value, 2)}
        for name, value in sorted(sums.items(), key=lambda kv: kv[1], reverse=True)
    ]

# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@app.route('/')
def serve_index():
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
def get_accounts():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT account_id, net_liquidation, day_pnl
        FROM current_state
        ORDER BY account_id
    ''')
    rows = c.fetchall()
    info = get_account_info(c)
    conn.close()

    refresh_date = get_config_val('last_refresh', '')
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
def get_portfolio():
    account_id = request.args.get('account_id', 'ALL')

    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT MAX(date) AS max_date FROM daily_snapshot')
    latest_date = c.fetchone()['max_date']
    if not latest_date:
        conn.close()
        return jsonify({'error': 'No data'}), 404

    if account_id == 'ALL':
        c.execute('''SELECT * FROM daily_snapshot WHERE date = ?''', (latest_date,))
    else:
        c.execute('''SELECT * FROM daily_snapshot WHERE date = ? AND account_id = ?''',
                  (latest_date, account_id))

    rows = c.fetchall()
    if not rows:
        conn.close()
        return jsonify({'error': 'No holdings found'}), 404

    summary = account_summary(c, account_id)

    c.execute('SELECT DISTINCT account_id FROM daily_snapshot WHERE date = ?', (latest_date,))
    account_ids = [r['account_id'] for r in c.fetchall()]
    info = get_account_info(c)
    conn.close()

    holdings = [build_holding(r) for r in rows]
    securities_value = sum(h['market_value'] for h in holdings)

    # Cash is a first-class holding, so every allocation slice (cash included)
    # sums to 100% of securities + cash. Percentages are computed client-side.
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
        # NAV decomposition straight from EquitySummaryInBase
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
def targets():
    """Per-account rebalance target weights, persisted in the config table.

    GET  ?account_id=X         → {'account_id': X, 'targets': {TICKER: pct, ...}}
    POST {account_id, targets} → saves and echoes the stored targets
    """
    if request.method == 'POST':
        body = request.get_json(silent=True) or {}
        account_id = body.get('account_id', 'ALL')
        raw = body.get('targets', {})
        # Keep only finite, non-negative numbers
        clean = {}
        for k, v in (raw.items() if isinstance(raw, dict) else []):
            try:
                pct = float(v)
            except (TypeError, ValueError):
                continue
            if pct >= 0:
                clean[str(k)] = round(pct, 4)
        set_config_val(f'targets_{account_id}', json.dumps(clean))
        return jsonify({'account_id': account_id, 'targets': clean})

    account_id = request.args.get('account_id', 'ALL')
    raw = get_config_val(f'targets_{account_id}', '{}')
    try:
        saved = json.loads(raw)
    except Exception:
        saved = {}
    return jsonify({'account_id': account_id, 'targets': saved})

@app.route('/api/trigger-refresh')
def trigger_refresh():
    """Manual refresh with rate limiting."""
    last_manual = get_config_val('last_manual_refresh', '0')
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

    set_config_val('last_manual_refresh', str(now_ts))

    if config['mock_mode']:
        conn = get_db()
        new_date = mock_data.incremental_update(conn)
        conn.close()
        set_config_val('last_refresh', new_date)
        return jsonify({
            'status': 'ok',
            'date': new_date,
            'mode': 'mock',
            'message': f'Mock data refreshed to {new_date}'
        })

    new_date, is_new, error = refresh_real_data()
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
        'mode': 'live',
        'message': message
    })

@app.route('/api/status')
def get_status():
    last_refresh = get_config_val('last_refresh', 'Never')
    last_manual = get_config_val('last_manual_refresh', '0')

    now_ts = time.time()
    try:
        last_ts = float(last_manual)
        cooldown_remaining = max(0, int(config['refresh_cooldown'] - (now_ts - last_ts)))
    except (ValueError, TypeError):
        cooldown_remaining = 0

    return jsonify({
        'last_refresh': last_refresh,
        'mode': 'mock' if config['mock_mode'] else 'live',
        'refresh_cooldown_remaining': cooldown_remaining,
    })

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
def setup_scheduler():
    """Hourly self-check instead of a fixed daily time.

    refresh_real_data is gated on the expected report date (computed in the
    market timezone), so the hourly tick costs one DB query when data is
    current and only queries IBKR when a new report should exist. This needs
    no schedule configuration and behaves identically in any server timezone;
    with a shared database, multiple instances dedupe against each other.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        if config['mock_mode']:
            def mock_refresh():
                conn = get_db()
                mock_data.incremental_update(conn)
                conn.close()
            scheduler.add_job(mock_refresh, 'interval', days=1, id='daily_mock_refresh')
        else:
            scheduler.add_job(
                refresh_real_data, 'interval', hours=1,
                next_run_time=datetime.now() + timedelta(seconds=15),
                id='hourly_refresh',
            )
        scheduler.start()
    except ImportError:
        pass  # APScheduler optional

init_db()
_migrate_to_current_state()
ensure_data()
setup_scheduler()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', config['port']))
    app.run(debug=bool(config['debug']), host='0.0.0.0', port=port)
