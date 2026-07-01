"""Storage abstraction: SQLite/PostgreSQL, S3, user management, encryption.

Multi-tenant: every data table is scoped by user_id. Deployment config stays
in YAML; user data (flex_token, flex_query_id, targets, etc.) lives in DB.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

_pg_pool = None  # psycopg2 ThreadedConnectionPool, initialised lazily


def connect(config):
    """Return a DB-API 2.0 connection (SQLite or PostgreSQL).

    Both backends return dict-like rows accessible by column name or index.
    The PG connection auto-converts ? placeholders to %s so existing SQL works.
    PostgreSQL uses a thread-safe connection pool.
    """
    db_type = config.get('db_type', 'sqlite')
    if db_type == 'postgres':
        import psycopg2
        import psycopg2.extras

        global _pg_pool
        if _pg_pool is None:
            from psycopg2.pool import ThreadedConnectionPool
            _pg_pool = ThreadedConnectionPool(
                2, 10, config['postgres_url'])

        class _CompatCursor(psycopg2.extras.RealDictCursor):
            def execute(self, query, vars=None):
                return super().execute(query.replace('?', '%s'), vars)

        conn = _pg_pool.getconn()
        conn.cursor_factory = _CompatCursor
        return conn
    else:
        conn = sqlite3.connect(config.get('db_path', 'ibkr_portfolio.db'))
        conn.row_factory = sqlite3.Row
        return conn


def return_conn(conn, config):
    """Return a connection to the pool (PG) or close it (SQLite)."""
    if config.get('db_type') == 'postgres':
        global _pg_pool
        if _pg_pool is not None:
            _pg_pool.putconn(conn)
        else:
            conn.close()
    else:
        conn.close()


# ---------------------------------------------------------------------------
# Schema (all tables scoped by user_id where applicable)
# ---------------------------------------------------------------------------

SCHEMA = {
    # --- Multi-tenant data tables ---
    'daily_snapshot': '''(
        user_id     TEXT NOT NULL,
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
        prev_close_price REAL,
        prev_close_quantity REAL,
        multiplier  REAL,
        strike      REAL,
        expiry      TEXT,
        put_call    TEXT,
        underlying_symbol TEXT,
        listing_exchange  TEXT,
        currency    TEXT DEFAULT 'USD',
        PRIMARY KEY (user_id, date, account_id, ticker)
    )''',
    'current_state': '''(
        user_id           TEXT NOT NULL,
        account_id        TEXT NOT NULL,
        net_liquidation   REAL,
        cash_balance      REAL,
        stock_value       REAL,
        options_value     REAL,
        dividend_accruals REAL,
        interest_accruals REAL,
        day_pnl           REAL,
        PRIMARY KEY (user_id, account_id)
    )''',
    'account_info': '''(
        user_id        TEXT NOT NULL,
        account_id     TEXT NOT NULL,
        alias          TEXT,
        account_type   TEXT,
        syep           TEXT,
        drip           TEXT,
        tax_lot_method TEXT,
        date_opened    TEXT,
        PRIMARY KEY (user_id, account_id)
    )''',
    'config': '''(
        user_id TEXT NOT NULL,
        key     TEXT NOT NULL,
        value   TEXT,
        PRIMARY KEY (user_id, key)
    )''',

    # --- Identity & session tables ---
    'users': '''(
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
        last_login       TEXT NOT NULL
    )''',
    'sessions': '''(
        session_id   TEXT PRIMARY KEY,
        user_id      TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        last_used_at TEXT NOT NULL,
        ip_address   TEXT,
        user_agent   TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )''',

    # --- Audit / observability ---
    # Note: id uses TEXT (UUID) for cross-DB portability.
    # PostgreSQL-compatible — no AUTOINCREMENT which is SQLite-only.
    'user_fetch_log': '''(
        id           TEXT PRIMARY KEY,
        user_id      TEXT NOT NULL,
        status       TEXT NOT NULL,
        error_code   TEXT,
        error_detail TEXT,
        report_date  TEXT,
        duration_ms  INTEGER,
        created_at   TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )''',

}

# Separate index DDL (SQLite doesn't support IF NOT EXISTS on indexes,
# so we create them in init_db after the tables exist).
INDEXES = [
    'CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)',
    'CREATE INDEX IF NOT EXISTS idx_fetch_log_user ON user_fetch_log(user_id, created_at DESC)',
]


def init_db(conn):
    """Create tables and indexes if they don't exist. Works on SQLite and PG."""
    c = conn.cursor()
    for table, body in SCHEMA.items():
        c.execute(f'CREATE TABLE IF NOT EXISTS {table} {body}')
    for idx_sql in INDEXES:
        try:
            c.execute(idx_sql)
        except Exception:
            pass  # index may already exist on PG
    conn.commit()


# ---------------------------------------------------------------------------
# Config helpers (user-scoped)
# ---------------------------------------------------------------------------
def get_config_val(conn, user_id, key, default=None):
    c = conn.cursor()
    c.execute('SELECT value FROM config WHERE user_id = ? AND key = ?',
              (user_id, key))
    row = c.fetchone()
    return row['value'] if row else default


def set_config_val(conn, user_id, key, value):
    c = conn.cursor()
    c.execute('DELETE FROM config WHERE user_id = ? AND key = ?',
              (user_id, key))
    c.execute('INSERT INTO config (user_id, key, value) VALUES (?, ?, ?)',
              (user_id, key, str(value)))
    conn.commit()


# ---------------------------------------------------------------------------
# Flex token encryption (Fernet — symmetric, authenticated)
# ---------------------------------------------------------------------------
def _get_fernet(config):
    from cryptography.fernet import Fernet
    return Fernet(config['flex_encryption_key'].encode())


def encrypt_flex_token(config, plaintext: str) -> str:
    if not plaintext:
        return ''
    return _get_fernet(config).encrypt(plaintext.encode()).decode()


def decrypt_flex_token(config, ciphertext: str) -> str:
    if not ciphertext:
        return ''
    return _get_fernet(config).decrypt(ciphertext.encode()).decode()


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------
def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def get_user_by_google_sub(conn, google_sub: str):
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE google_sub = ?', (google_sub,))
    return c.fetchone()


def get_user_by_id(conn, user_id: str):
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    return c.fetchone()


def create_user(conn, user_id: str, email: str, name: str, google_sub: str):
    """Insert a new user row. Returns the created row."""
    now = _utc_now()
    c = conn.cursor()
    c.execute('''INSERT INTO users
        (user_id, email, name, google_sub, created_at, last_login)
        VALUES (?, ?, ?, ?, ?, ?)''',
        (user_id, email, name, google_sub, now, now))
    conn.commit()
    return get_user_by_id(conn, user_id)


def update_user_login(conn, user_id: str, name: str):
    """Update last_login and name on each OAuth callback."""
    c = conn.cursor()
    c.execute('''UPDATE users SET last_login = ?, name = ?
                 WHERE user_id = ?''', (_utc_now(), name, user_id))
    conn.commit()


def set_user_flex_credentials(conn, config, user_id: str,
                               flex_token: str, flex_query_id: str):
    """Encrypt and store Flex credentials, set status to healthy."""
    token_enc = encrypt_flex_token(config, flex_token)
    c = conn.cursor()
    c.execute('''UPDATE users
                 SET flex_token_enc = ?, flex_query_id = ?,
                     flex_status = 'healthy'
                 WHERE user_id = ?''',
              (token_enc, flex_query_id, user_id))
    conn.commit()
    return get_user_by_id(conn, user_id)


def set_user_flex_status(conn, user_id: str, status: str):
    c = conn.cursor()
    c.execute('UPDATE users SET flex_status = ? WHERE user_id = ?',
              (status, user_id))
    conn.commit()


def get_active_users_with_credentials(conn):
    """Users eligible for scheduled refresh."""
    c = conn.cursor()
    c.execute('''SELECT * FROM users
                 WHERE is_active = 1
                   AND flex_token_enc != ''
                   AND flex_query_id != ''
                   AND flex_status IN ('healthy', 'error')''')
    return c.fetchall()


def get_user_market_timezone(conn, user_id: str, default_tz: str) -> str:
    user = get_user_by_id(conn, user_id)
    if user and user.get('market_timezone'):
        return user['market_timezone']
    return default_tz


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
def create_session(conn, session_id: str, user_id: str,
                   ip_address: str = None, user_agent: str = None):
    now = _utc_now()
    c = conn.cursor()
    c.execute('''INSERT INTO sessions
        (session_id, user_id, created_at, last_used_at, ip_address, user_agent)
        VALUES (?, ?, ?, ?, ?, ?)''',
        (session_id, user_id, now, now, ip_address, user_agent))
    conn.commit()


def validate_session(conn, session_id: str, user_id: str) -> bool:
    """Return True if the session row exists and matches the user."""
    c = conn.cursor()
    c.execute('''SELECT user_id FROM sessions
                 WHERE session_id = ? AND user_id = ?''',
              (session_id, user_id))
    row = c.fetchone()
    if not row:
        return False
    # Touch last_used_at lazily (only if > 1 hour stale)
    c.execute('''UPDATE sessions SET last_used_at = ?
                 WHERE session_id = ? AND last_used_at < ?''',
              (_utc_now(), session_id,
               datetime.now(timezone.utc).replace(hour=-1).strftime('%Y-%m-%dT%H:%M:%SZ')))
    conn.commit()
    return True


def delete_session(conn, session_id: str):
    c = conn.cursor()
    c.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
    conn.commit()


def cleanup_expired_sessions(conn):
    """Delete sessions older than 30 days."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    c = conn.cursor()
    c.execute('DELETE FROM sessions WHERE last_used_at < ?', (cutoff,))
    conn.commit()


# ---------------------------------------------------------------------------
# Fetch log helpers
# ---------------------------------------------------------------------------
def log_fetch_success(conn, user_id: str, report_date: str, duration_ms: int):
    import uuid
    c = conn.cursor()
    c.execute('''INSERT INTO user_fetch_log
        (id, user_id, status, report_date, duration_ms, created_at)
        VALUES (?, ?, 'success', ?, ?, ?)''',
        (str(uuid.uuid4()), user_id, report_date, duration_ms, _utc_now()))
    conn.commit()


def log_fetch_error(conn, user_id: str, error_code: str, error_detail: str,
                    report_date: str = None, duration_ms: int = None):
    import uuid
    c = conn.cursor()
    c.execute('''INSERT INTO user_fetch_log
        (id, user_id, status, error_code, error_detail, report_date,
         duration_ms, created_at)
        VALUES (?, ?, 'error', ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), user_id, error_code, error_detail, report_date,
         duration_ms, _utc_now()))
    conn.commit()


def get_user_fetch_errors(conn, user_id: str, limit: int = 5):
    c = conn.cursor()
    c.execute('''SELECT * FROM user_fetch_log
                 WHERE user_id = ? AND status = 'error'
                 ORDER BY created_at DESC LIMIT ?''', (user_id, limit))
    return c.fetchall()


def count_consecutive_failures(conn, user_id: str) -> int:
    """Count consecutive error rows since the last success."""
    c = conn.cursor()
    c.execute('''SELECT status FROM user_fetch_log
                 WHERE user_id = ? ORDER BY created_at DESC LIMIT 20''',
              (user_id,))
    count = 0
    for row in c.fetchall():
        if row['status'] == 'error':
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# S3 raw XML store
# ---------------------------------------------------------------------------
class S3Store:
    def __init__(self, config):
        self.enabled = bool(config.get('s3_bucket', ''))
        if not self.enabled:
            return
        import boto3
        self.client = boto3.client(
            's3',
            region_name=config.get('s3_region', 'us-east-1'),
            endpoint_url=config.get('s3_endpoint') or None,
            aws_access_key_id=config.get('s3_access_key') or None,
            aws_secret_access_key=config.get('s3_secret_key') or None,
        )
        self.bucket = config['s3_bucket']
        self.prefix = config.get('s3_prefix', 'flex_raw/')

    def _key(self, date_str):
        return f'{self.prefix}{date_str}.xml'

    def save_raw_xml(self, date_str, xml_text):
        if not self.enabled:
            return
        key = self._key(date_str)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=xml_text.encode('utf-8'),
            ContentType='application/xml',
        )

    def get_raw_xml(self, date_str):
        if not self.enabled:
            return None
        key = self._key(date_str)
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
            return resp['Body'].read().decode('utf-8')
        except Exception:
            return None

    def verify_raw_xml(self, date_str) -> bool:
        if not self.enabled:
            return True
        key = self._key(date_str)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False
