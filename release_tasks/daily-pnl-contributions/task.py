"""Create and backfill the daily P&L contribution store from raw XML."""

from dataclasses import dataclass
from collections import Counter
import os
from pathlib import Path
import sys

import boto3
from botocore.config import Config
import psycopg2
from psycopg2.extras import RealDictCursor


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / 'backend'))

import flex_parser  # noqa: E402


@dataclass(frozen=True)
class ContributionValue:
    user_id: str
    report_date: str
    account_id: str
    conid: str
    ticker: str
    full_name: str
    asset_class: str
    day_pnl: float
    prev_close_price: float
    prev_close_quantity: float
    currency: str


def required_environment(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise RuntimeError(f'Required environment variable is missing: {name}')
    return value


def create_s3_client():
    return boto3.client(
        's3',
        region_name=os.environ.get('S3_REGION', '').strip() or 'us-east-1',
        endpoint_url=os.environ.get('S3_ENDPOINT', '').strip() or None,
        aws_access_key_id=os.environ.get('S3_ACCESS_KEY', '').strip() or None,
        aws_secret_access_key=os.environ.get('S3_SECRET_KEY', '').strip() or None,
        config=Config(
            connect_timeout=int(os.environ.get('S3_CONNECT_TIMEOUT', '3')),
            read_timeout=int(os.environ.get('S3_READ_TIMEOUT', '10')),
            retries={
                'mode': 'standard',
                'total_max_attempts': int(
                    os.environ.get('S3_TOTAL_MAX_ATTEMPTS', '3')
                ),
            },
        ),
    )


def s3_key(user_id, report_date):
    prefix = os.environ.get('S3_PREFIX', '').strip() or 'flex_raw/'
    return f'{prefix}{user_id}/{report_date}.xml'


def download_xml(client, bucket, user_id, report_date):
    response = client.get_object(
        Bucket=bucket,
        Key=s3_key(user_id, report_date),
    )
    return response['Body'].read().decode('utf-8')


def load_snapshots(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('''SELECT DISTINCT user_id, date
                          FROM positions
                          ORDER BY user_id, date''')
        snapshots = [
            (row['user_id'], row['date']) for row in cursor.fetchall()
        ]
    conn.commit()
    return snapshots


def parse_snapshot(xml_text, user_id, report_date):
    data = flex_parser.parse_flex_xml(xml_text)
    if data.get('date') != report_date:
        raise ValueError(
            f'Raw XML report date mismatch for {user_id}: '
            f'expected {report_date}, got {data.get("date")}'
        )

    values = []
    keys = set()
    for account in data['accounts']:
        account_id = account['account_id']
        for contribution in account.get('day_pnl_contributions', []):
            key = (
                user_id,
                report_date,
                account_id,
                contribution['conid'],
                contribution['ticker'],
            )
            if key in keys:
                raise ValueError(
                    f'Raw XML contains a duplicate contribution key: {key}'
                )
            keys.add(key)
            values.append(ContributionValue(
                user_id=user_id,
                report_date=report_date,
                account_id=account_id,
                conid=contribution['conid'],
                ticker=contribution['ticker'],
                full_name=contribution['full_name'],
                asset_class=contribution['asset_class'],
                day_pnl=contribution['day_pnl'],
                prev_close_price=contribution['prev_close_price'],
                prev_close_quantity=contribution['prev_close_quantity'],
                currency=contribution['currency'],
            ))
    return values


def prepare_values(conn, s3_client, bucket):
    snapshots = load_snapshots(conn)
    values = []
    for user_id, report_date in snapshots:
        values.extend(parse_snapshot(
            download_xml(s3_client, bucket, user_id, report_date),
            user_id,
            report_date,
        ))
    return snapshots, values


def apply_schema(conn):
    with conn.cursor() as cursor:
        cursor.execute('''CREATE TABLE IF NOT EXISTS daily_pnl_contributions (
            user_id TEXT NOT NULL REFERENCES users(user_id),
            date TEXT NOT NULL,
            account_id TEXT NOT NULL,
            conid TEXT NOT NULL DEFAULT '',
            ticker TEXT NOT NULL,
            full_name TEXT,
            asset_class TEXT,
            day_pnl DOUBLE PRECISION,
            prev_close_price DOUBLE PRECISION,
            prev_close_quantity DOUBLE PRECISION,
            currency TEXT DEFAULT 'USD',
            PRIMARY KEY (user_id, date, account_id, conid, ticker)
        )''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS
                          idx_daily_pnl_contributions_date
                          ON daily_pnl_contributions(user_id, date)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS
                          idx_daily_pnl_contributions_account
                          ON daily_pnl_contributions(
                              user_id, account_id, date
                          )''')
    conn.commit()


def write_and_verify(conn, snapshots, values):
    expected_counts = Counter(
        (value.user_id, value.report_date) for value in values
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            for user_id, report_date in snapshots:
                cursor.execute('''DELETE FROM daily_pnl_contributions
                                  WHERE user_id = %s AND date = %s''',
                               (user_id, report_date))

            for value in values:
                cursor.execute('''INSERT INTO daily_pnl_contributions (
                    user_id, date, account_id, conid, ticker, full_name,
                    asset_class, day_pnl, prev_close_price,
                    prev_close_quantity, currency
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''', (
                    value.user_id,
                    value.report_date,
                    value.account_id,
                    value.conid,
                    value.ticker,
                    value.full_name,
                    value.asset_class,
                    value.day_pnl,
                    value.prev_close_price,
                    value.prev_close_quantity,
                    value.currency,
                ))

            for user_id, report_date in snapshots:
                cursor.execute('''SELECT COUNT(*) AS count
                                  FROM daily_pnl_contributions
                                  WHERE user_id = %s AND date = %s''',
                               (user_id, report_date))
                stored_count = cursor.fetchone()['count']
                expected_count = expected_counts[(user_id, report_date)]
                if stored_count != expected_count:
                    raise RuntimeError(
                        f'Contribution verification failed for '
                        f'{user_id}/{report_date}: expected {expected_count}, '
                        f'found {stored_count}'
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def main():
    postgres_url = required_environment('POSTGRES_URL')
    bucket = required_environment('S3_BUCKET')
    conn = psycopg2.connect(postgres_url)
    try:
        apply_schema(conn)
        snapshots, values = prepare_values(
            conn,
            create_s3_client(),
            bucket,
        )
        write_and_verify(conn, snapshots, values)
    finally:
        conn.close()

    print(
        'Daily P&L contribution migration completed and verified: '
        f'{len(snapshots)} snapshots, {len(values)} contributions.'
    )


if __name__ == '__main__':
    main()
