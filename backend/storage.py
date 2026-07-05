"""Storage: PostgreSQL connection pool, user/session/targets CRUD, S3."""

from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Database connection (PostgreSQL only)
# ---------------------------------------------------------------------------

_pg_pool = None


def connect(config):
    """Return a dict-like DB-API connection from the PostgreSQL pool."""
    import psycopg2
    import psycopg2.extras

    global _pg_pool
    if _pg_pool is None:
        from psycopg2.pool import ThreadedConnectionPool
        _pg_pool = ThreadedConnectionPool(2, 10, config['postgres_url'])

    class _CompatCursor(psycopg2.extras.RealDictCursor):
        def execute(self, query, vars=None):
            return super().execute(query.replace('?', '%s'), vars)

    conn = _pg_pool.getconn()
    conn.cursor_factory = _CompatCursor
    return conn


def return_conn(conn, config):
    """Return a connection to the pool."""
    global _pg_pool
    if _pg_pool is not None:
        _pg_pool.putconn(conn)
    else:
        conn.close()


# ---------------------------------------------------------------------------
# Flex token encryption
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
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def get_user_by_google_sub(conn, google_sub: str):
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE google_sub = ?', (google_sub,))
    return c.fetchone()


def get_user_by_id(conn, user_id: str):
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    return c.fetchone()


def create_user(conn, user_id: str, email: str, name: str, google_sub: str):
    now = _utc_now()
    c = conn.cursor()
    c.execute('''INSERT INTO users
        (user_id, email, name, google_sub, created_at, last_login)
        VALUES (?, ?, ?, ?, ?, ?)''',
        (user_id, email, name, google_sub, now, now))
    conn.commit()
    return get_user_by_id(conn, user_id)


def update_user_login(conn, user_id: str, name: str):
    c = conn.cursor()
    c.execute('UPDATE users SET last_login = ?, name = ? WHERE user_id = ?',
              (_utc_now(), name, user_id))
    conn.commit()


def set_user_flex_credentials(conn, config, user_id: str,
                               flex_token: str, flex_query_id: str):
    token_enc = encrypt_flex_token(config, flex_token)
    c = conn.cursor()
    c.execute('''UPDATE users
                 SET flex_token_enc = ?, flex_query_id = ?, flex_status = 'healthy'
                 WHERE user_id = ?''',
              (token_enc, flex_query_id, user_id))
    conn.commit()
    return get_user_by_id(conn, user_id)


def set_user_flex_status(conn, user_id: str, status: str):
    c = conn.cursor()
    c.execute('UPDATE users SET flex_status = ? WHERE user_id = ?',
              (status, user_id))
    conn.commit()


def set_user_last_refresh(conn, user_id: str, report_date: str):
    c = conn.cursor()
    c.execute('UPDATE users SET last_refresh = ? WHERE user_id = ?',
              (report_date, user_id))
    conn.commit()


def set_user_fetch_at(conn, user_id: str, ts: float):
    c = conn.cursor()
    c.execute('UPDATE users SET last_fetch_at = ? WHERE user_id = ?',
              (ts, user_id))
    conn.commit()


def set_user_manual_at(conn, user_id: str, ts: float):
    c = conn.cursor()
    c.execute('UPDATE users SET last_manual_at = ? WHERE user_id = ?',
              (ts, user_id))
    conn.commit()


def get_active_users_with_credentials(conn):
    c = conn.cursor()
    c.execute('''SELECT * FROM users
                 WHERE is_active = 1
                   AND flex_token_enc != ''
                   AND flex_query_id != ''
                   AND flex_status IN ('healthy', 'error')''')
    return c.fetchall()


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
    c = conn.cursor()
    c.execute('SELECT user_id FROM sessions WHERE session_id = ? AND user_id = ?',
              (session_id, user_id))
    if not c.fetchone():
        return False
    c.execute('''UPDATE sessions SET last_used_at = ?
                 WHERE session_id = ? AND last_used_at < ?''',
              (_utc_now(), session_id,
               (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')))
    conn.commit()
    return True


def delete_session(conn, session_id: str):
    c = conn.cursor()
    c.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
    conn.commit()


def cleanup_expired_sessions(conn):
    """Delete sessions older than 30 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    c = conn.cursor()
    c.execute('DELETE FROM sessions WHERE last_used_at < ?', (cutoff,))
    conn.commit()


# ---------------------------------------------------------------------------
# Targets CRUD
# ---------------------------------------------------------------------------

def get_targets(conn, user_id: str, account_id: str = 'ALL') -> dict:
    """Return {ticker: weight} for a user+account."""
    c = conn.cursor()
    c.execute('SELECT ticker, weight FROM targets WHERE user_id = ? AND account_id = ?',
              (user_id, account_id))
    return {row['ticker']: row['weight'] for row in c.fetchall()}


def set_targets(conn, user_id: str, account_id: str, targets: dict):
    """Replace all targets for a user+account with the given {ticker: weight} dict."""
    c = conn.cursor()
    c.execute('DELETE FROM targets WHERE user_id = ? AND account_id = ?',
              (user_id, account_id))
    for ticker, weight in targets.items():
        c.execute('INSERT INTO targets (user_id, account_id, ticker, weight) VALUES (?, ?, ?, ?)',
                  (user_id, account_id, ticker, weight))
    conn.commit()


# ---------------------------------------------------------------------------
# Fetch log helpers
# ---------------------------------------------------------------------------

def log_fetch_success(conn, user_id: str, report_date: str, duration_ms: int):
    c = conn.cursor()
    c.execute('''INSERT INTO fetch_log
        (user_id, status, report_date, duration_ms, created_at)
        VALUES (?, 'success', ?, ?, ?)''',
        (user_id, report_date, duration_ms, _utc_now()))
    conn.commit()


def log_fetch_error(conn, user_id: str, error_code: str, error_detail: str,
                    report_date: str = None, duration_ms: int = None):
    c = conn.cursor()
    c.execute('''INSERT INTO fetch_log
        (user_id, status, error_code, error_detail, report_date, duration_ms, created_at)
        VALUES (?, 'error', ?, ?, ?, ?, ?)''',
        (user_id, error_code, error_detail, report_date, duration_ms, _utc_now()))
    conn.commit()


def get_user_fetch_errors(conn, user_id: str, limit: int = 5):
    c = conn.cursor()
    c.execute('''SELECT * FROM fetch_log
                 WHERE user_id = ? AND status = 'error'
                 ORDER BY created_at DESC LIMIT ?''', (user_id, limit))
    return c.fetchall()


def count_consecutive_failures(conn, user_id: str) -> int:
    c = conn.cursor()
    c.execute('''SELECT status FROM fetch_log
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

    def _key(self, user_id, date_str):
        return f'{self.prefix}{user_id}/{date_str}.xml'

    def save_raw_xml(self, user_id, date_str, xml_text):
        if not self.enabled:
            return
        key = self._key(user_id, date_str)
        self.client.put_object(
            Bucket=self.bucket, Key=key,
            Body=xml_text.encode('utf-8'),
            ContentType='application/xml',
        )

    def get_raw_xml(self, user_id, date_str):
        if not self.enabled:
            return None
        key = self._key(user_id, date_str)
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
            return resp['Body'].read().decode('utf-8')
        except Exception:
            return None

    def verify_raw_xml(self, user_id, date_str) -> bool:
        if not self.enabled:
            return True
        key = self._key(user_id, date_str)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False
