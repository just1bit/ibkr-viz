-- IBKR Portfolio Viz — PostgreSQL schema
-- Run: psql -d <dbname> -f backend/schema.sql

-- ---------------------------------------------------------------------------
-- 1. users — identity, credentials, refresh state
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id          TEXT PRIMARY KEY,
    email            TEXT NOT NULL,
    name             TEXT NOT NULL DEFAULT '',
    google_sub       TEXT UNIQUE NOT NULL,
    flex_token_enc   TEXT NOT NULL DEFAULT '',
    flex_query_id    TEXT NOT NULL DEFAULT '',
    flex_status      TEXT NOT NULL DEFAULT 'not_configured',
    market_timezone  TEXT,
    is_admin         INTEGER NOT NULL DEFAULT 0,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    last_login       TEXT NOT NULL,
    last_refresh     TEXT,
    last_fetch_at    DOUBLE PRECISION,
    last_manual_at   DOUBLE PRECISION,
    xml_native_data_version INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- 2. sessions — server-side session validation
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    created_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    ip_address   TEXT,
    user_agent   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- ---------------------------------------------------------------------------
-- 3. accounts — per-account NAV + metadata
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    user_id           TEXT NOT NULL REFERENCES users(user_id),
    account_id        TEXT NOT NULL,
    alias             TEXT,
    account_type      TEXT,
    syep              TEXT,
    drip              TEXT,
    tax_lot_method    TEXT,
    date_opened       TEXT,
    net_liquidation   DOUBLE PRECISION,
    cash_balance      DOUBLE PRECISION,
    stock_value       DOUBLE PRECISION,
    options_value     DOUBLE PRECISION,
    dividend_accruals DOUBLE PRECISION,
    interest_accruals DOUBLE PRECISION,
    previous_net_liquidation DOUBLE PRECISION,
    day_pnl           DOUBLE PRECISION,
    PRIMARY KEY (user_id, account_id)
);

-- ---------------------------------------------------------------------------
-- 4. positions — daily position snapshot
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS positions (
    user_id            TEXT NOT NULL REFERENCES users(user_id),
    date               TEXT NOT NULL,
    account_id         TEXT NOT NULL,
    conid              TEXT,
    ticker             TEXT NOT NULL,
    full_name          TEXT,
    asset_class        TEXT,
    side               TEXT,
    quantity           DOUBLE PRECISION,
    market_value       DOUBLE PRECISION,
    mark_price         DOUBLE PRECISION,
    cost_price         DOUBLE PRECISION,
    cost_basis         DOUBLE PRECISION,
    unrealized_pnl     DOUBLE PRECISION,
    day_pnl            DOUBLE PRECISION,
    prev_close_price   DOUBLE PRECISION,
    prev_close_quantity DOUBLE PRECISION,
    xml_percent_of_nav DOUBLE PRECISION,
    multiplier         DOUBLE PRECISION,
    strike             DOUBLE PRECISION,
    expiry             TEXT,
    put_call           TEXT,
    underlying_symbol  TEXT,
    listing_exchange   TEXT,
    currency           TEXT DEFAULT 'USD',
    PRIMARY KEY (user_id, date, account_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_positions_date ON positions(user_id, date);
CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(user_id, account_id, date);

-- ---------------------------------------------------------------------------
-- 5. targets — per-user per-account target allocation weights
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS targets (
    user_id    TEXT NOT NULL REFERENCES users(user_id),
    account_id TEXT NOT NULL DEFAULT 'ALL',
    ticker     TEXT NOT NULL,
    weight     DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (user_id, account_id, ticker)
);

-- ---------------------------------------------------------------------------
-- 6. fetch_log — data refresh audit trail
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fetch_log (
    id           SERIAL PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    status       TEXT NOT NULL,
    error_code   TEXT,
    error_detail TEXT,
    report_date  TEXT,
    duration_ms  INTEGER,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fetch_log_user ON fetch_log(user_id, created_at);
