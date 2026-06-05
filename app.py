"""IBKR Portfolio Viz — Flask backend.

Single-file Flask application with SQLite storage and APScheduler for daily refresh.
Runs in mock mode by default (no IBKR credentials needed).
"""

import os
import time
import json
from collections import defaultdict
from datetime import datetime

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
    defaults = {
        'mock_mode': True,
        'flex_token': '',
        'flex_query_id': '',
        'db_type': 'sqlite',
        'db_path': os.path.join(BASE_DIR, 'ibkr_portfolio.db'),
        'postgres_url': '',
        'refresh_hour': 17,
        'refresh_minute': 0,
        'refresh_cooldown': 600,
        's3_bucket': '',
        's3_endpoint': '',
        's3_region': 'us-east-1',
        's3_access_key': '',
        's3_secret_key': '',
    }
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            user = yaml.safe_load(f) or {}
        defaults.update(user)
    return defaults

config = load_config()
app = Flask(__name__, static_folder=None)
s3_store = storage.S3Store(config)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    return storage.connect(config)

def init_db():
    conn = get_db()
    storage.init_db(conn)
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

def get_account_types():
    raw = get_config_val('account_types', '{}')
    try:
        return json.loads(raw)
    except Exception:
        return {}

def refresh_real_data():
    """Fetch and store real IBKR Flex data.

    Pipeline (each step must succeed before the next):
      1. Fetch XML from IBKR → saved to LOCAL file immediately by flex_client
      2. Upload local file → S3, then verify the S3 object exists
      3. Parse XML in memory
      4. Insert parsed data into database
      5. Delete local file (only on full success)

    If any step fails, the local raw file is preserved so we never lose data
    that cost an IBKR rate-limited fetch.
    """
    token = config.get('flex_token', '')
    query_id = config.get('flex_query_id', '')
    if not token or not query_id:
        return None, 'Flex token or query ID not configured'

    today = datetime.now().strftime('%Y-%m-%d')
    local_path = os.path.join(BASE_DIR, f'flex_raw_{today}.xml')

    # Check if today's data already exists — avoid redundant IBKR calls
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) AS cnt FROM nav_history WHERE date = ?', (today,))
    if c.fetchone()['cnt'] > 0:
        set_config_val('last_refresh', today)
        conn.commit()
        conn.close()
        return today, None
    conn.close()

    # --- Step 1: Fetch + save locally (save happens inside get_flex_xml) ---
    try:
        xml_text = flex_client.get_flex_xml(token, query_id, save_path=local_path)
    except Exception as e:
        return None, f'IBKR fetch failed: {e}'

    # --- Step 2: Upload to S3 + verify ---
    s3_store.save_raw_xml(today, xml_text)
    if not s3_store.verify_raw_xml(today):
        return None, f'S3 upload verification failed — raw XML preserved at {local_path}'

    # --- Step 3: Parse ---
    try:
        data = flex_parser.parse_flex_xml(xml_text, today)
    except Exception as e:
        return None, f'Parse failed: {e} — raw XML preserved at {local_path}'

    # --- Step 4: Insert into database ---
    try:
        conn = get_db()
        c = conn.cursor()

        account_types = get_account_types()
        for acc in data['accounts']:
            aid = acc['account_id']
            account_types[aid] = acc.get('account_type', 'MARGIN')

            c.execute('''INSERT INTO nav_history
                (date, account_id, net_liquidation, cash_balance,
                 gross_pnl, day_pnl, leverage, margin_util)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (today, aid, acc['net_liquidation'], acc['cash_balance'],
                 acc['gross_pnl'], acc['day_pnl'],
                 acc['leverage'], acc['margin_util']))

            for h in acc['holdings']:
                c.execute('''INSERT INTO daily_snapshot
                    (date, account_id, ticker, full_name, asset_class, sector,
                     quantity, market_value, cost_price, currency)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (today, aid, h['ticker'], h['full_name'], h['asset_class'],
                     h['sector'], h['quantity'], h['market_value'],
                     h['cost_price'], h['currency']))

        set_config_val('account_types', json.dumps(account_types))
        set_config_val('last_refresh', today)
        conn.commit()
        conn.close()
    except Exception as e:
        return None, f'Database insert failed: {e} — raw XML preserved at {local_path}'

    # --- Step 5: Clean up local file on success ---
    if os.path.exists(local_path):
        os.remove(local_path)

    return today, None

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def margin_color(pct):
    if pct < 40: return 'green'
    if pct <= 70: return 'yellow'
    return 'red'

# ---------------------------------------------------------------------------
# Portfolio builders (colors are assigned by the frontend, not here)
# ---------------------------------------------------------------------------
def account_summary(cursor, date, account_id):
    """NAV / cash / P&L totals for one account, or all accounts merged.

    Always returns numeric values (missing rows default to 0)."""
    if account_id == 'ALL':
        cursor.execute('''SELECT SUM(net_liquidation) AS total_nav, SUM(cash_balance) AS total_cash,
                          SUM(gross_pnl) AS total_gross_pnl, SUM(day_pnl) AS total_day_pnl
                          FROM nav_history WHERE date = ?''', (date,))
    else:
        cursor.execute('''SELECT net_liquidation AS total_nav, cash_balance AS total_cash,
                          gross_pnl AS total_gross_pnl, day_pnl AS total_day_pnl
                          FROM nav_history WHERE date = ? AND account_id = ?''', (date, account_id))
    row = cursor.fetchone()
    keys = ('total_nav', 'total_cash', 'total_gross_pnl', 'total_day_pnl')
    return {k: (row[k] if row and row[k] is not None else 0) for k in keys}


def build_holding(row):
    """Map a daily_snapshot row to a holding dict with unrealized P&L."""
    mv, cost, qty = row['market_value'], row['cost_price'], row['quantity']
    basis = cost * qty if cost and qty else 0
    pnl = mv - basis if basis else 0
    return {
        'ticker': row['ticker'],
        'full_name': row['full_name'],
        'asset_class': row['asset_class'],
        'sector': row['sector'] or 'Other',
        'quantity': qty,
        'market_value': mv,
        'cost_price': cost,
        'unrealized_pnl': round(pnl, 2),
        'unrealized_pnl_pct': round(pnl / basis * 100, 2) if basis > 0 else 0,
        'currency': row['currency'],
        'account_id': row['account_id'],
    }


def cash_holding(amount, account_id):
    """Cash represented as a holding so it joins the allocation breakdown."""
    return {
        'ticker': 'CASH', 'full_name': 'Cash', 'asset_class': 'CASH', 'sector': 'Cash',
        'quantity': amount, 'market_value': amount, 'cost_price': None,
        'unrealized_pnl': 0, 'unrealized_pnl_pct': 0, 'currency': 'USD',
        'account_id': account_id,
    }


def group_summary(holdings, field, total):
    """Sum holdings by a field (asset_class / sector), sorted by value desc."""
    sums = defaultdict(float)
    for h in holdings:
        sums[h[field] or 'Other'] += h['market_value']
    return [
        {
            'name': name,
            'value': round(value, 2),
            'pct': round(value / total * 100, 2) if total else 0,
        }
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
        SELECT n.account_id, n.net_liquidation, n.date,
               n.gross_pnl, n.day_pnl, n.leverage, n.margin_util
        FROM nav_history n
        WHERE n.date = (SELECT MAX(date) FROM nav_history WHERE account_id = n.account_id)
        ORDER BY n.account_id
    ''')
    rows = c.fetchall()
    conn.close()

    account_types = get_account_types()
    accounts = []
    for r in rows:
        accounts.append({
            'account_id': r['account_id'],
            'net_liquidation': r['net_liquidation'],
            'date': r['date'],
            'gross_pnl': r['gross_pnl'],
            'day_pnl': r['day_pnl'],
            'leverage': r['leverage'],
            'margin_util': r['margin_util'],
            'account_type': account_types.get(r['account_id'], 'MARGIN'),
        })
    return jsonify({'accounts': accounts})

@app.route('/api/portfolio')
def get_portfolio():
    account_id = request.args.get('account_id', 'ALL')

    conn = get_db()
    c = conn.cursor()

    # Get latest date
    c.execute('SELECT MAX(date) AS max_date FROM daily_snapshot')
    latest_date = c.fetchone()['max_date']
    if not latest_date:
        conn.close()
        return jsonify({'error': 'No data'}), 404

    # Build query
    if account_id == 'ALL':
        c.execute('''SELECT * FROM daily_snapshot WHERE date = ?''', (latest_date,))
    else:
        c.execute('''SELECT * FROM daily_snapshot WHERE date = ? AND account_id = ?''',
                  (latest_date, account_id))

    rows = c.fetchall()
    if not rows:
        conn.close()
        return jsonify({'error': 'No holdings found'}), 404

    summary = account_summary(c, latest_date, account_id)

    c.execute('SELECT DISTINCT account_id FROM daily_snapshot WHERE date = ?', (latest_date,))
    account_ids = [r['account_id'] for r in c.fetchall()]
    conn.close()

    holdings = [build_holding(r) for r in rows]
    securities_value = sum(h['market_value'] for h in holdings)

    # Cash is a first-class holding. Weights are taken against securities + cash,
    # so every slice (cash included) sums to 100%.
    cash_value = round(max(summary['total_cash'], 0), 2)
    alloc_total = securities_value + cash_value
    if cash_value > 0:
        holdings.append(cash_holding(cash_value, account_id))

    for h in holdings:
        h['weight'] = round(h['market_value'] / alloc_total * 100, 2) if alloc_total else 0
    holdings.sort(key=lambda h: h['market_value'], reverse=True)

    return jsonify({
        'date': latest_date,
        'account_id': account_id,
        'accounts': account_ids,
        'holdings': holdings,
        'summary': {
            'total_value': round(securities_value, 2),
            'allocation_total': round(alloc_total, 2),
            'net_liquidation': round(summary['total_nav'], 2),
            'total_cash': round(summary['total_cash'], 2),
            'total_day_pnl': round(summary['total_day_pnl'], 2),
            'total_gross_pnl': round(summary['total_gross_pnl'], 2),
            'cash_gap': round(summary['total_nav'] - securities_value, 2),
        },
        'asset_class_summary': group_summary(holdings, 'asset_class', alloc_total),
        'sector_summary': group_summary(holdings, 'sector', alloc_total),
        'ticker_summary': [
            {
                'name': h['ticker'],
                'value': h['market_value'],
                'pct': h['weight'],
                'full_name': h['full_name'],
                'asset_class': h['asset_class'],
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

@app.route('/api/margin')
def get_margin():
    account_id = request.args.get('account_id', 'ALL')

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT MAX(date) AS max_date FROM nav_history')
    latest_date = c.fetchone()['max_date']

    if account_id == 'ALL':
        c.execute('''SELECT SUM(net_liquidation) as total_nav,
                     AVG(leverage) as avg_lev,
                     AVG(margin_util) as avg_margin
                     FROM nav_history WHERE date = ?''', (latest_date,))
    else:
        c.execute('''SELECT net_liquidation as total_nav,
                     leverage as avg_lev,
                     margin_util as avg_margin
                     FROM nav_history WHERE date = ? AND account_id = ?''',
                  (latest_date, account_id))

    row = c.fetchone()
    conn.close()

    if not row or not row['total_nav']:
        return jsonify({'error': 'No data'}), 404

    leverage = round(row['avg_lev'], 2) if row['avg_lev'] else 0
    margin_u = round(row['avg_margin'], 2) if row['avg_margin'] else 0

    account_types = get_account_types()
    is_cash = False
    if account_id != 'ALL':
        is_cash = account_types.get(account_id, 'MARGIN') == 'CASH'

    return jsonify({
        'account_id': account_id,
        'leverage': leverage,
        'margin_util': margin_u,
        'is_cash_account': is_cash,
        'color_margin': margin_color(margin_u),
    })

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
    else:
        new_date, error = refresh_real_data()
        if error:
            return jsonify({'error': error}), 500
        return jsonify({
            'status': 'ok',
            'date': new_date,
            'mode': 'live',
            'message': f'Live data refreshed to {new_date}'
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
    """Initialize APScheduler for daily refresh."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        hour = config['refresh_hour']
        minute = config['refresh_minute']
        def scheduled_refresh():
            if config['mock_mode']:
                conn = get_db()
                mock_data.incremental_update(conn)
                conn.close()
            else:
                refresh_real_data()

        scheduler.add_job(
            func=scheduled_refresh,
            trigger='cron',
            hour=hour,
            minute=minute,
            id='daily_refresh'
        )
        scheduler.start()
    except ImportError:
        pass  # APScheduler optional

# Initialize
init_db()
ensure_data()
setup_scheduler()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5123))
    app.run(debug=True, host='0.0.0.0', port=port)
