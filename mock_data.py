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
    # (ticker, full_name, asset_class, sector, qty, price, account_id)
    ('QQQ', 'Invesco QQQ Trust', 'ETF', 'Technology', 120, 480.50, 'U123456'),
    ('AAPL', 'Apple Inc.', 'STOCK', 'Technology', 80, 183.20, 'U123456'),
    ('MSFT', 'Microsoft Corporation', 'STOCK', 'Technology', 55, 425.10, 'U123456'),
    ('AMZN', 'Amazon.com Inc.', 'STOCK', 'Consumer Cyclical', 120, 178.30, 'U123456'),
    ('GOOGL', 'Alphabet Inc.', 'STOCK', 'Communication', 40, 163.50, 'U123456'),
    ('NVDA', 'NVIDIA Corporation', 'STOCK', 'Technology', 25, 880.20, 'U123456'),
    ('IAU', 'iShares Gold Trust', 'ETF', 'Commodities', 400, 44.80, 'U234567'),
    ('SPY', 'SPDR S&P 500 ETF', 'ETF', 'Broad Market', 55, 525.60, 'U234567'),
    ('GLD', 'SPDR Gold Shares', 'ETF', 'Commodities', 60, 215.30, 'U234567'),
    ('BND', 'Vanguard Total Bond Market ETF', 'BOND', 'Fixed Income', 200, 71.50, 'U234567'),
    ('JPM', 'JPMorgan Chase & Co.', 'STOCK', 'Financial', 60, 198.40, 'U123456'),
    ('JNJ', 'Johnson & Johnson', 'STOCK', 'Healthcare', 40, 156.70, 'U345678'),
    ('XOM', 'Exxon Mobil Corporation', 'STOCK', 'Energy', 70, 118.20, 'U345678'),
    ('PEP', 'PepsiCo Inc.', 'STOCK', 'Consumer Defensive', 30, 172.80, 'U345678'),
    ('RING', 'Direxion Gold Miners ETF', 'ETF', 'Commodities', 150, 42.50, 'U345678'),
    ('VTI', 'Vanguard Total Stock Market ETF', 'ETF', 'Broad Market', 40, 265.30, 'U345678'),
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
    still needed so day P/L (vs. the previous day) and total P/L (vs. the
    first day) have a baseline, and so incremental refresh has a prior row.

    Returns:
        dates: list of date strings 'YYYY-MM-DD'
        nav_data: {account_id: [(date, nav, cash, gross_pnl, day_pnl, leverage, margin_util), ...]}
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
            gross_pnl = nav - start_nav
            # Leverage varies slowly around 1.5-2.8
            leverage = 1.5 + 0.5 * math.sin(i * 0.01) + random.gauss(0, 0.15)
            leverage = round(max(1.0, min(3.5, leverage)), 2)
            # Margin utilization ~20-45%
            margin_util = 25 + 10 * math.sin(i * 0.015 + 1) + random.gauss(0, 3)
            margin_util = round(max(5, min(60, margin_util)), 1)

            rows.append((d, nav, cash, gross_pnl, day_pnl, leverage, margin_util))
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
        ticker      TEXT NOT NULL,
        full_name   TEXT,
        asset_class TEXT,
        sector      TEXT,
        quantity    REAL,
        market_value REAL,
        cost_price  REAL,
        currency    TEXT DEFAULT 'USD',
        PRIMARY KEY (date, account_id, ticker)
    )''')

    c.execute('''CREATE TABLE nav_history (
        date            TEXT NOT NULL,
        account_id      TEXT NOT NULL,
        net_liquidation REAL,
        cash_balance    REAL,
        gross_pnl       REAL,
        day_pnl         REAL,
        leverage        REAL,
        margin_util     REAL,
        PRIMARY KEY (date, account_id)
    )''')

    c.execute('''CREATE TABLE config (
        key   TEXT PRIMARY KEY,
        value TEXT
    )''')

    date_strs, nav_data = generate_nav_history(days=400, start_nav=100000)

    # Insert daily_snapshot rows
    for aid in ACCOUNT_IDS:
        holdings = [h for h in MOCK_HOLDINGS if h[6] == aid]
        total_mv = sum(h[4] * h[5] for h in holdings)

        for date_str in date_strs:
            nav_row = next(r for r in nav_data[aid] if r[0] == date_str)
            nav_val = nav_row[1]
            scale = nav_val / 100000  # scale holdings proportionally with NAV

            for ticker, name, aclass, sector, qty, base_price, _ in holdings:
                # Add noise to individual prices
                price = base_price * scale * (0.95 + random.random() * 0.10)
                mv = round(qty * price, 2)
                cost = round(base_price * 0.85 * qty, 2)

                c.execute('''INSERT INTO daily_snapshot
                    (date, account_id, ticker, full_name, asset_class, sector,
                     quantity, market_value, cost_price, currency)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (date_str, aid, ticker, name, aclass, sector,
                     qty, mv, cost, 'USD'))

    # Insert nav_history rows
    for aid in ACCOUNT_IDS:
        for row in nav_data[aid]:
            c.execute('''INSERT INTO nav_history
                (date, account_id, net_liquidation, cash_balance,
                 gross_pnl, day_pnl, leverage, margin_util)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (row[0], aid, row[1], row[2], row[3], row[4], row[5], row[6]))

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
        c.execute('''SELECT net_liquidation, cash_balance, leverage, margin_util
                     FROM nav_history WHERE date = ? AND account_id = ?''',
                  (last_date, aid))
        prev = c.fetchone()
        if not prev:
            continue

        prev_nav, prev_cash, prev_lev, prev_margin = prev

        # Small random change
        daily_ret = random.gauss(0.0004, 0.012)  # ~ daily return + noise
        new_nav = round(prev_nav * (1 + daily_ret), 2)
        new_cash = round(prev_cash * (1 + random.gauss(0.0, 0.005)), 2)
        day_pnl = round(new_nav - prev_nav, 2)
        c.execute('SELECT net_liquidation FROM nav_history WHERE account_id = ? ORDER BY date ASC LIMIT 1', (aid,))
        initial_nav = c.fetchone()[0]
        gross_pnl = round(new_nav - initial_nav, 2)

        new_lev = round(prev_lev + random.gauss(0, 0.05), 2)
        new_lev = max(1.0, min(3.5, new_lev))
        new_margin = round(prev_margin + random.gauss(0, 1.0), 1)
        new_margin = max(5, min(60, new_margin))

        c.execute('''INSERT INTO nav_history
            (date, account_id, net_liquidation, cash_balance,
             gross_pnl, day_pnl, leverage, margin_util)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (next_date, aid, new_nav, new_cash, gross_pnl, day_pnl, new_lev, new_margin))

        # Insert daily_snapshot rows
        c.execute('''SELECT ticker, full_name, asset_class, sector, quantity,
                     cost_price, currency, account_id
                     FROM daily_snapshot WHERE date = ? AND account_id = ?''',
                  (last_date, aid))
        holdings = c.fetchall()

        for ticker, name, aclass, sector, qty, cost, currency, acc_id in holdings:
            price_jitter = 1 + random.gauss(0, 0.015)
            new_mv = round(qty * (0 if not cost else cost * 1.2) * price_jitter, 2)
            new_mv = max(0, new_mv)
            c.execute('''INSERT INTO daily_snapshot
                (date, account_id, ticker, full_name, asset_class, sector,
                 quantity, market_value, cost_price, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (next_date, acc_id, ticker, name, aclass, sector,
                 qty, new_mv, cost, currency))

    c.execute('DELETE FROM config WHERE key = ?', ('last_refresh',))
    c.execute('INSERT INTO config (key, value) VALUES (?, ?)',
              ('last_refresh', next_date))
    conn.commit()
    return next_date
