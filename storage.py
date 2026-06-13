"""Storage abstraction: SQLite/PostgreSQL + S3 raw data store."""

import sqlite3


def connect(config):
    """Return a DB-API 2.0 connection (SQLite or PostgreSQL).

    Both backends return dict-like rows accessible by column name or index.
    The PG connection auto-converts ? placeholders to %s so existing SQL works.
    """
    db_type = config.get('db_type', 'sqlite')
    if db_type == 'postgres':
        import psycopg2
        import psycopg2.extras

        class _CompatCursor(psycopg2.extras.RealDictCursor):
            def execute(self, query, vars=None):
                return super().execute(query.replace('?', '%s'), vars)

        conn = psycopg2.connect(
            config['postgres_url'],
            cursor_factory=_CompatCursor,
        )
        return conn
    else:
        conn = sqlite3.connect(config.get('db_path', 'ibkr_portfolio.db'))
        conn.row_factory = sqlite3.Row
        return conn


# Shared between init_db and mock_data's seed (which drops + recreates).
SCHEMA = {
    'daily_snapshot': '''(
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
        PRIMARY KEY (date, account_id, ticker)
    )''',
    'current_state': '''(
        account_id        TEXT PRIMARY KEY,
        net_liquidation   REAL,
        cash_balance      REAL,
        stock_value       REAL,
        options_value     REAL,
        dividend_accruals REAL,
        interest_accruals REAL,
        day_pnl           REAL
    )''',
    'account_info': '''(
        account_id     TEXT PRIMARY KEY,
        alias          TEXT,
        account_type   TEXT,
        syep           TEXT,
        drip           TEXT,
        tax_lot_method TEXT,
        date_opened    TEXT
    )''',
    'config': '''(
        key   TEXT PRIMARY KEY,
        value TEXT
    )''',
}


def init_db(conn):
    """Create tables if they don't exist. Works on SQLite and PostgreSQL."""
    c = conn.cursor()
    for table, body in SCHEMA.items():
        c.execute(f'CREATE TABLE IF NOT EXISTS {table} {body}')
    conn.commit()


# ---------------------------------------------------------------------------
# Config helpers (cross-DB compatible — uses DELETE + INSERT)
# ---------------------------------------------------------------------------
def get_config_val(conn, key, default=None):
    c = conn.cursor()
    c.execute('SELECT value FROM config WHERE key = ?', (key,))
    row = c.fetchone()
    return row['value'] if row else default


def set_config_val(conn, key, value):
    c = conn.cursor()
    c.execute('DELETE FROM config WHERE key = ?', (key,))
    c.execute('INSERT INTO config (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()


# ---------------------------------------------------------------------------
# S3 raw XML store (optional)
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
        """Confirm an object exists in S3 after upload. Returns True if found."""
        if not self.enabled:
            return True
        key = self._key(date_str)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False
