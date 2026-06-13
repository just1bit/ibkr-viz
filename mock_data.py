"""Mock data generator for IBKR Portfolio Viz.
Generates realistic demo data so the app works without real IBKR credentials.
Uses deterministic random seed for reproducibility.
"""

import random
import math
from datetime import datetime, timedelta

import storage

random.seed(42)

# ---------------------------------------------------------------------------
# Mock holdings — stocks/ETFs plus one option so every UI path has data
# ---------------------------------------------------------------------------
MOCK_HOLDINGS = [
    # (ticker, full_name, asset_class, qty, price, multiplier,
    #  strike, expiry, put_call, underlying, exchange, account_id)
    ('QQQ', 'Invesco QQQ Trust', 'ETF', 120, 480.50, 1, 0, '', '', '', 'NASDAQ', 'U123456'),
    ('AAPL', 'Apple Inc.', 'STOCK', 80, 183.20, 1, 0, '', '', '', 'NASDAQ', 'U123456'),
    ('MSFT', 'Microsoft Corporation', 'STOCK', 55, 425.10, 1, 0, '', '', '', 'NASDAQ', 'U123456'),
    ('AMZN', 'Amazon.com Inc.', 'STOCK', 120, 178.30, 1, 0, '', '', '', 'NASDAQ', 'U123456'),
    ('GOOGL', 'Alphabet Inc.', 'STOCK', 40, 163.50, 1, 0, '', '', '', 'NASDAQ', 'U123456'),
    ('NVDA', 'NVIDIA Corporation', 'STOCK', 25, 880.20, 1, 0, '', '', '', 'NASDAQ', 'U123456'),
    ('JPM', 'JPMorgan Chase & Co.', 'STOCK', 60, 198.40, 1, 0, '', '', '', 'NYSE', 'U123456'),
    ('SPY   261218C00550000', 'SPY 18DEC26 550 C', 'OPTION', 2, 32.50, 100,
     550, '2026-12-18', 'C', 'SPY', 'CBOE', 'U123456'),
    ('IAU', 'iShares Gold Trust', 'ETF', 400, 44.80, 1, 0, '', '', '', 'ARCA', 'U234567'),
    ('SPY', 'SPDR S&P 500 ETF', 'ETF', 55, 525.60, 1, 0, '', '', '', 'ARCA', 'U234567'),
    ('GLD', 'SPDR Gold Shares', 'ETF', 60, 215.30, 1, 0, '', '', '', 'ARCA', 'U234567'),
    ('BND', 'Vanguard Total Bond Market ETF', 'BOND', 200, 71.50, 1, 0, '', '', '', 'NASDAQ', 'U234567'),
    ('ASML', 'ASML Holding NV', 'STOCK', 40, 156.70, 1, 0, '', '', '', 'NASDAQ', 'U345678'),
    ('TSM', 'Taiwan Semiconductor ADR', 'STOCK', 70, 118.20, 1, 0, '', '', '', 'NYSE', 'U345678'),
    ('SAP', 'SAP SE ADR', 'STOCK', 30, 172.80, 1, 0, '', '', '', 'NYSE', 'U345678'),
    ('RING', 'iShares MSCI Global Gold Miners ETF', 'ETF', 150, 42.50, 1, 0, '', '', '', 'NASDAQ', 'U345678'),
    ('VTI', 'Vanguard Total Stock Market ETF', 'ETF', 40, 265.30, 1, 0, '', '', '', 'ARCA', 'U345678'),
]

ACCOUNT_IDS = ['U123456', 'U234567', 'U345678']

# Per-account cash proportions (for variety)
ACCOUNT_CASH_RATIO = {'U123456': 0.08, 'U234567': 0.06, 'U345678': 0.12}

# Per-account profile rows (account_info table)
ACCOUNT_PROFILES = {
    'U123456': ('Growth', 'MARGIN', 'enabled', 'No', 'FIFO', '2023-03-14'),
    'U234567': ('Income', 'MARGIN', 'enabled', 'Yes', 'FIFO', '2022-08-01'),
    'U345678': ('Global', 'CASH', 'not enrolled', 'No', 'FIFO', '2024-01-09'),
}


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


def _nav_components(aid, nav, cash, options_value):
    """Split a NAV into the EquitySummary-style components we store."""
    dividend_accruals = round(nav * 0.0004, 2)
    interest_accruals = round(-nav * 0.0001, 2)
    stock = round(nav - cash - options_value - dividend_accruals - interest_accruals, 2)
    return stock, dividend_accruals, interest_accruals


def _insert_nav_row(c, date_str, aid, nav, cash, day_pnl, options_value):
    stock, div_acc, int_acc = _nav_components(aid, nav, cash, options_value)
    c.execute('''INSERT INTO nav_history
        (date, account_id, net_liquidation, cash_balance, stock_value,
         options_value, dividend_accruals, interest_accruals, day_pnl)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (date_str, aid, nav, cash, stock, options_value,
         div_acc, int_acc, day_pnl))


def _insert_cash_report(c, date_str, aid, nav, day_index):
    """Deterministic but plausible MTD/YTD cash-flow figures."""
    mtd = (day_index % 21) + 1
    ytd = (day_index % 252) + 1
    scale = nav / 100000
    c.execute('''INSERT INTO cash_report
        (date, account_id,
         commissions_mtd, commissions_ytd,
         broker_interest_mtd, broker_interest_ytd,
         dividends_mtd, dividends_ytd,
         payment_in_lieu_mtd, payment_in_lieu_ytd,
         withholding_tax_mtd, withholding_tax_ytd,
         deposit_withdrawals_mtd, deposit_withdrawals_ytd,
         net_trades_sales_mtd, net_trades_sales_ytd,
         net_trades_purchases_mtd, net_trades_purchases_ytd)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (date_str, aid,
         round(-1.2 * mtd * scale, 2), round(-1.2 * ytd * scale, 2),
         round(-2.4 * mtd * scale, 2), round(-2.4 * ytd * scale, 2),
         round(3.1 * mtd * scale, 2), round(3.1 * ytd * scale, 2),
         round(0.4 * mtd * scale, 2), round(0.4 * ytd * scale, 2),
         round(-0.9 * mtd * scale, 2), round(-0.9 * ytd * scale, 2),
         round(500 * (mtd // 7) * scale, 2), round(500 * (ytd // 21) * scale, 2),
         round(1800 * mtd * scale, 2), round(1800 * ytd * scale, 2),
         round(-2100 * mtd * scale, 2), round(-2100 * ytd * scale, 2)))


def _insert_snapshot_row(c, date_str, aid, h, idx, price, day_pnl):
    """Insert one daily_snapshot row from a MOCK_HOLDINGS entry."""
    (ticker, name, aclass, qty, _base, mult,
     strike, expiry, put_call, underlying, exchange, _acct) = h
    mv = round(qty * price * mult, 2)
    cost_price = round(price * 0.85, 2)
    cost_basis = round(cost_price * qty * mult, 2)
    prev_price = round(price - day_pnl / (qty * mult), 4) if qty else price
    c.execute('''INSERT INTO daily_snapshot
        (date, account_id, conid, ticker, full_name, asset_class,
         side, quantity, market_value, mark_price,
         cost_price, cost_basis, unrealized_pnl, day_pnl,
         prev_close_price, prev_close_quantity, multiplier,
         strike, expiry, put_call, underlying_symbol,
         listing_exchange, currency)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (date_str, aid, str(100000 + idx), ticker, name, aclass,
         'Long', qty, mv, price,
         cost_price, cost_basis, round(mv - cost_basis, 2), day_pnl,
         prev_price, qty, mult, strike, expiry, put_call, underlying,
         exchange, 'USD'))


def seed_database(conn) -> None:
    """Seed the database with mock data. Recreates tables first."""
    c = conn.cursor()

    for table, body in storage.SCHEMA.items():
        c.execute(f'DROP TABLE IF EXISTS {table}')
        c.execute(f'CREATE TABLE {table} {body}')

    date_strs, nav_data = generate_nav_history(days=400, start_nav=100000)

    # Insert daily_snapshot rows
    for aid in ACCOUNT_IDS:
        holdings = [h for h in MOCK_HOLDINGS if h[11] == aid]

        for date_str in date_strs:
            nav_row = next(r for r in nav_data[aid] if r[0] == date_str)
            nav_val = nav_row[1]
            scale = nav_val / 100000  # scale holdings proportionally with NAV

            for idx, h in enumerate(holdings):
                qty, base_price, mult = h[3], h[4], h[5]
                # Add noise to individual prices
                price = round(base_price * scale * (0.95 + random.random() * 0.10), 2)
                day_pnl = round(qty * price * mult * random.gauss(0, 0.01), 2)
                _insert_snapshot_row(c, date_str, aid, h, idx, price, day_pnl)

    # Insert nav_history + cash_report rows
    for aid in ACCOUNT_IDS:
        option_mvs = {}
        if any(h[2] == 'OPTION' for h in MOCK_HOLDINGS if h[11] == aid):
            c.execute('''SELECT date, SUM(market_value) AS mv FROM daily_snapshot
                         WHERE account_id = ? AND asset_class = 'OPTION'
                         GROUP BY date''', (aid,))
            option_mvs = {r['date']: r['mv'] for r in c.fetchall()}
        for i, row in enumerate(nav_data[aid]):
            date_str, nav, cash, day_pnl = row
            _insert_nav_row(c, date_str, aid, nav, cash, day_pnl,
                            round(option_mvs.get(date_str, 0), 2))
            _insert_cash_report(c, date_str, aid, nav, i)

    # Insert account_info rows
    for aid, (alias, atype, syep, drip, lot, opened) in ACCOUNT_PROFILES.items():
        c.execute('''INSERT INTO account_info
            (account_id, alias, account_type, syep, drip, tax_lot_method,
             date_opened)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (aid, alias, atype, syep, drip, lot, opened))

    # Insert config (table freshly created, plain INSERT is safe)
    c.execute('INSERT INTO config (key, value) VALUES (?, ?)',
              ('last_refresh', date_strs[-1]))
    c.execute('INSERT INTO config (key, value) VALUES (?, ?)',
              ('last_manual_refresh', '0'))

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
    day_index = (datetime.strptime(next_date, '%Y-%m-%d') - datetime(2025, 1, 1)).days

    for aid in ACCOUNT_IDS:
        # Get previous NAV
        c.execute('''SELECT net_liquidation, cash_balance
                     FROM nav_history WHERE date = ? AND account_id = ?''',
                  (last_date, aid))
        prev = c.fetchone()
        if not prev:
            continue

        prev_nav, prev_cash = prev['net_liquidation'], prev['cash_balance']

        # Small random change
        daily_ret = random.gauss(0.0004, 0.012)  # ~ daily return + noise
        new_nav = round(prev_nav * (1 + daily_ret), 2)
        new_cash = round(prev_cash * (1 + random.gauss(0.0, 0.005)), 2)
        day_pnl = round(new_nav - prev_nav, 2)

        # Insert daily_snapshot rows, tracking the new option value for nav
        c.execute('''SELECT * FROM daily_snapshot
                     WHERE date = ? AND account_id = ?''', (last_date, aid))
        holdings = c.fetchall()

        options_value = 0.0
        for prev_row in holdings:
            r = dict(prev_row)
            price_jitter = 1 + random.gauss(0, 0.015)
            qty, mult = r['quantity'], r['multiplier'] or 1
            new_price = round((r['mark_price'] or 0) * price_jitter, 2)
            new_mv = round(qty * new_price * mult, 2)
            if r['asset_class'] == 'OPTION':
                options_value += new_mv
            c.execute('''INSERT INTO daily_snapshot
                (date, account_id, conid, ticker, full_name, asset_class,
                 side, quantity, market_value, mark_price,
                 cost_price, cost_basis, unrealized_pnl, day_pnl,
                 prev_close_price, prev_close_quantity, multiplier,
                 strike, expiry, put_call, underlying_symbol,
                 listing_exchange, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (next_date, aid, r['conid'], r['ticker'], r['full_name'],
                 r['asset_class'], r['side'], qty, new_mv, new_price,
                 r['cost_price'], r['cost_basis'],
                 round(new_mv - (r['cost_basis'] or 0), 2),
                 round(new_mv - (r['market_value'] or 0), 2),
                 r['mark_price'], qty, mult,
                 r['strike'], r['expiry'], r['put_call'],
                 r['underlying_symbol'], r['listing_exchange'], r['currency']))

        _insert_nav_row(c, next_date, aid, new_nav, new_cash, day_pnl,
                        round(options_value, 2))
        _insert_cash_report(c, next_date, aid, new_nav, day_index)

    c.execute('DELETE FROM config WHERE key = ?', ('last_refresh',))
    c.execute('INSERT INTO config (key, value) VALUES (?, ?)',
              ('last_refresh', next_date))
    conn.commit()
    return next_date
