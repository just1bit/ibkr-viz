"""Mock data generator for IBKR Portfolio Viz.
Generates realistic demo data so the app works without real IBKR credentials.
Uses deterministic random seed for reproducibility.
"""

import json
import random
import math
from datetime import datetime, timedelta

random.seed(42)

# ---------------------------------------------------------------------------
# Mock holdings — 16 tickers with realistic allocations
# ---------------------------------------------------------------------------
MOCK_HOLDINGS = [
    # (ticker, full_name, asset_class, qty, price, account_id)
    ('QQQ', 'Invesco QQQ Trust', 'ETF', 120, 480.50, 'U123456'),
    ('AAPL', 'Apple Inc.', 'STOCK', 80, 183.20, 'U123456'),
    ('MSFT', 'Microsoft Corporation', 'STOCK', 55, 425.10, 'U123456'),
    ('AMZN', 'Amazon.com Inc.', 'STOCK', 120, 178.30, 'U123456'),
    ('GOOGL', 'Alphabet Inc.', 'STOCK', 40, 163.50, 'U123456'),
    ('NVDA', 'NVIDIA Corporation', 'STOCK', 25, 880.20, 'U123456'),
    ('IAU', 'iShares Gold Trust', 'ETF', 400, 44.80, 'U234567'),
    ('SPY', 'SPDR S&P 500 ETF', 'ETF', 55, 525.60, 'U234567'),
    ('GLD', 'SPDR Gold Shares', 'ETF', 60, 215.30, 'U234567'),
    ('BND', 'Vanguard Total Bond Market ETF', 'BOND', 200, 71.50, 'U234567'),
    ('JPM', 'JPMorgan Chase & Co.', 'STOCK', 60, 198.40, 'U123456'),
    ('ASML', 'ASML Holding NV', 'STOCK', 40, 156.70, 'U345678'),
    ('TSM', 'Taiwan Semiconductor ADR', 'STOCK', 70, 118.20, 'U345678'),
    ('SAP', 'SAP SE ADR', 'STOCK', 30, 172.80, 'U345678'),
    ('RING', 'iShares MSCI Global Gold Miners ETF', 'ETF', 150, 42.50, 'U345678'),
    ('VTI', 'Vanguard Total Stock Market ETF', 'ETF', 40, 265.30, 'U345678'),
]

ACCOUNT_IDS = ['U123456', 'U234567', 'U345678']

# Per-account cash proportions (for variety)
ACCOUNT_CASH_RATIO = {'U123456': 0.08, 'U234567': 0.06, 'U345678': 0.12}

# Per-account account types (margin vs cash)
ACCOUNT_TYPES = {'U123456': 'MARGIN', 'U234567': 'MARGIN', 'U345678': 'CASH'}


def _random_walk(n_days, start_val, annual_return, annual_vol):
    """Generate a geometric random walk price series."""
    daily_return = annual_return / 252
    daily_vol = annual_vol / math.sqrt(252)
    values = [start_val]
    for _ in range(n_days - 1):
        r = random.gauss(daily_return, daily_vol)
        values.append(values[-1] * (1 + r))
    return values


def generate_nav_history(days=400, start_nav=100000):
    """Generate daily NAV / cash history for all accounts.

    The product no longer charts returns over time, but a short history is
    still needed so day P/L (vs. the previous day) has a baseline, and so
    incremental refresh has a prior row.

    Returns:
        dates: list of date strings 'YYYY-MM-DD'
        nav_data: {account_id: [(date, nav, cash, day_pnl), ...]}
    """
    end_date = datetime(2026, 5, 2)
    dates = [(end_date - timedelta(days=i)) for i in range(days - 1, -1, -1)]
    date_strs = [d.strftime('%Y-%m-%d') for d in dates]

    nav_data = {}
    for aid in ACCOUNT_IDS:
        cash_ratio = ACCOUNT_CASH_RATIO[aid]
        nav_series = _random_walk(days, start_nav, 0.10, 0.18)

        rows = []
        for i, (d, nav) in enumerate(zip(date_strs, nav_series)):
            cash = max(1000, nav * cash_ratio * (0.8 + random.random() * 0.4))
            day_pnl = nav - nav_series[i - 1] if i > 0 else 0

            rows.append((d, nav, cash, day_pnl))
        nav_data[aid] = rows

    return date_strs, nav_data


def seed_database(conn) -> None:
    """Seed the database with mock data. Recreates tables first."""
    c = conn.cursor()

    # Drop and recreate tables
    c.execute('DROP TABLE IF EXISTS daily_snapshot')
    c.execute('DROP TABLE IF EXISTS nav_history')
    c.execute('DROP TABLE IF EXISTS config')

    c.execute('''CREATE TABLE daily_snapshot (
        date        TEXT NOT NULL,
        account_id  TEXT NOT NULL,
        conid       TEXT,
        ticker      TEXT NOT NULL,
        full_name   TEXT,
        asset_class TEXT,
        side        TEXT,
        quantity    REAL,
        market_value REAL,
        mark_price  REAL,
        cost_price  REAL,
        cost_basis  REAL,
        unrealized_pnl REAL,
        day_pnl     REAL,
        currency    TEXT DEFAULT 'USD',
        PRIMARY KEY (date, account_id, ticker)
    )''')

    c.execute('''CREATE TABLE nav_history (
        date            TEXT NOT NULL,
        account_id      TEXT NOT NULL,
        net_liquidation REAL,
        cash_balance    REAL,
        day_pnl         REAL,
        PRIMARY KEY (date, account_id)
    )''')

    c.execute('''CREATE TABLE config (
        key   TEXT PRIMARY KEY,
        value TEXT
    )''')

    date_strs, nav_data = generate_nav_history(days=400, start_nav=100000)

    # Insert daily_snapshot rows
    for aid in ACCOUNT_IDS:
        holdings = [h for h in MOCK_HOLDINGS if h[5] == aid]

        for date_str in date_strs:
            nav_row = next(r for r in nav_data[aid] if r[0] == date_str)
            nav_val = nav_row[1]
            scale = nav_val / 100000  # scale holdings proportionally with NAV

            for idx, (ticker, name, aclass, qty, base_price, _) in enumerate(holdings):
                # Add noise to individual prices
                price = round(base_price * scale * (0.95 + random.random() * 0.10), 2)
                mv = round(qty * price, 2)
                cost_price = round(base_price * 0.85, 2)
                cost_basis = round(cost_price * qty, 2)
                day_pnl = round(mv * random.gauss(0, 0.01), 2)

                c.execute('''INSERT INTO daily_snapshot
                    (date, account_id, conid, ticker, full_name, asset_class,
                     side, quantity, market_value, mark_price,
                     cost_price, cost_basis, unrealized_pnl, day_pnl, currency)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (date_str, aid, str(100000 + idx), ticker, name, aclass,
                     'Long', qty, mv, price,
                     cost_price, cost_basis, round(mv - cost_basis, 2),
                     day_pnl, 'USD'))

    # Insert nav_history rows
    for aid in ACCOUNT_IDS:
        for row in nav_data[aid]:
            c.execute('''INSERT INTO nav_history
                (date, account_id, net_liquidation, cash_balance, day_pnl)
                VALUES (?, ?, ?, ?, ?)''',
                (row[0], aid, row[1], row[2], row[3]))

    # Insert config (table freshly created, plain INSERT is safe)
    c.execute('INSERT INTO config (key, value) VALUES (?, ?)',
              ('last_refresh', date_strs[-1]))
    c.execute('INSERT INTO config (key, value) VALUES (?, ?)',
              ('last_manual_refresh', '0'))
    c.execute('INSERT INTO config (key, value) VALUES (?, ?)',
              ('account_types', json.dumps(ACCOUNT_TYPES)))

    conn.commit()


def incremental_update(conn) -> str:
    """Add one new day of mock data. Returns the new date string."""
    c = conn.cursor()

    # Find the latest date
    c.execute('SELECT MAX(date) FROM nav_history')
    row = c.fetchone()
    if not row or not row[0]:
        seed_database(conn)
        c.execute('SELECT MAX(date) FROM nav_history')
        last_date = c.fetchone()[0]
    else:
        last_date = row[0]

    next_date = (datetime.strptime(last_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')

    for aid in ACCOUNT_IDS:
        # Get previous NAV
        c.execute('''SELECT net_liquidation, cash_balance
                     FROM nav_history WHERE date = ? AND account_id = ?''',
                  (last_date, aid))
        prev = c.fetchone()
        if not prev:
            continue

        prev_nav, prev_cash = prev

        # Small random change
        daily_ret = random.gauss(0.0004, 0.012)  # ~ daily return + noise
        new_nav = round(prev_nav * (1 + daily_ret), 2)
        new_cash = round(prev_cash * (1 + random.gauss(0.0, 0.005)), 2)
        day_pnl = round(new_nav - prev_nav, 2)

        c.execute('''INSERT INTO nav_history
            (date, account_id, net_liquidation, cash_balance, day_pnl)
            VALUES (?, ?, ?, ?, ?)''',
            (next_date, aid, new_nav, new_cash, day_pnl))

        # Insert daily_snapshot rows
        c.execute('''SELECT conid, ticker, full_name, asset_class, side,
                     quantity, market_value, cost_price, cost_basis, currency,
                     account_id
                     FROM daily_snapshot WHERE date = ? AND account_id = ?''',
                  (last_date, aid))
        holdings = c.fetchall()

        for (conid, ticker, name, aclass, side, qty, prev_mv,
             cost_price, cost_basis, currency, acc_id) in holdings:
            price_jitter = 1 + random.gauss(0, 0.015)
            new_mv = max(0, round(prev_mv * price_jitter, 2))
            new_price = round(new_mv / qty, 2) if qty else 0
            c.execute('''INSERT INTO daily_snapshot
                (date, account_id, conid, ticker, full_name, asset_class,
                 side, quantity, market_value, mark_price,
                 cost_price, cost_basis, unrealized_pnl, day_pnl, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (next_date, acc_id, conid, ticker, name, aclass,
                 side, qty, new_mv, new_price,
                 cost_price, cost_basis, round(new_mv - (cost_basis or 0), 2),
                 round(new_mv - prev_mv, 2), currency))

    c.execute('DELETE FROM config WHERE key = ?', ('last_refresh',))
    c.execute('INSERT INTO config (key, value) VALUES (?, ?)',
              ('last_refresh', next_date))
    conn.commit()
    return next_date
