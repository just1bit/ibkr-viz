"""Backfill XML-native portfolio values from the raw S3 archive.

This release task is intentionally independent from the Flask application.
It validates every available database snapshot against its exact raw XML file
before writing portfolio data, then performs and verifies all data updates in
one transaction. It creates no task-history or migration-version records.
"""

from collections import defaultdict
from dataclasses import dataclass
import os
from pathlib import Path
import sys

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / 'backend'))

import flex_parser  # noqa: E402


@dataclass(frozen=True)
class PositionValue:
    user_id: str
    report_date: str
    account_id: str
    ticker: str
    xml_percent_of_nav: float


@dataclass(frozen=True)
class AccountValue:
    user_id: str
    account_id: str
    previous_net_liquidation: float


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


def parse_and_validate_snapshot(xml_text, report_date, expected_positions,
                                expected_accounts=None):
    """Return direct XML values after strict date/key/completeness checks."""
    data = flex_parser.parse_flex_xml(xml_text)
    if data.get('date') != report_date:
        raise ValueError(
            f'Raw XML report date mismatch: expected {report_date}, '
            f'got {data.get("date")}'
        )

    accounts = {}
    positions = {}
    for account in data['accounts']:
        account_id = account['account_id']
        if account_id in accounts:
            raise ValueError('Raw XML contains a duplicate account')
        accounts[account_id] = account

        for holding in account['holdings']:
            key = (account_id, holding['ticker'])
            if key in positions:
                raise ValueError('Raw XML contains a duplicate position key')
            weight = holding.get('xml_percent_of_nav')
            if weight is None:
                raise ValueError('Raw XML position is missing percentOfNAV')
            positions[key] = weight

    if set(positions) != set(expected_positions):
        raise ValueError('Raw XML positions do not match the database snapshot')
    if expected_accounts is not None and set(accounts) != set(expected_accounts):
        raise ValueError('Raw XML accounts do not match the current database accounts')

    return accounts, positions


def load_database_inventory(conn):
    positions_by_snapshot = defaultdict(set)
    accounts_by_user = defaultdict(set)

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('''SELECT user_id, date, account_id, ticker
                          FROM positions
                          ORDER BY user_id, date, account_id, ticker''')
        for row in cursor.fetchall():
            positions_by_snapshot[(row['user_id'], row['date'])].add(
                (row['account_id'], row['ticker'])
            )

        cursor.execute('''SELECT user_id, MAX(date) AS report_date
                          FROM positions
                          GROUP BY user_id''')
        latest_by_user = {
            row['user_id']: row['report_date'] for row in cursor.fetchall()
        }

        cursor.execute('''SELECT user_id, account_id
                          FROM accounts
                          ORDER BY user_id, account_id''')
        for row in cursor.fetchall():
            accounts_by_user[row['user_id']].add(row['account_id'])

    conn.commit()
    return positions_by_snapshot, latest_by_user, accounts_by_user


def prepare_values(conn, s3_client, bucket):
    """Download and validate all source XML before any data write starts."""
    inventory, latest_by_user, accounts_by_user = load_database_inventory(conn)
    position_values = []
    account_values = []

    for (user_id, report_date), expected_positions in inventory.items():
        is_latest = latest_by_user[user_id] == report_date
        expected_accounts = accounts_by_user[user_id] if is_latest else None
        xml_text = download_xml(s3_client, bucket, user_id, report_date)
        accounts, positions = parse_and_validate_snapshot(
            xml_text,
            report_date,
            expected_positions,
            expected_accounts,
        )

        for (account_id, ticker), value in positions.items():
            position_values.append(PositionValue(
                user_id,
                report_date,
                account_id,
                ticker,
                value,
            ))

        if is_latest:
            for account_id, account in accounts.items():
                previous_nav = account.get('previous_net_liquidation')
                if previous_nav is None:
                    raise ValueError(
                        'Raw XML current account is missing previous NAV'
                    )
                account_values.append(AccountValue(
                    user_id,
                    account_id,
                    previous_nav,
                ))

    return position_values, account_values, len(inventory)


def apply_schema(conn):
    with conn.cursor() as cursor:
        cursor.execute('''ALTER TABLE accounts
                          ADD COLUMN IF NOT EXISTS previous_net_liquidation
                          DOUBLE PRECISION''')
        cursor.execute('''ALTER TABLE positions
                          ADD COLUMN IF NOT EXISTS xml_percent_of_nav
                          DOUBLE PRECISION''')
    conn.commit()


def write_and_verify(conn, position_values, account_values):
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            for value in position_values:
                cursor.execute('''UPDATE positions
                                  SET xml_percent_of_nav = %s
                                  WHERE user_id = %s AND date = %s
                                    AND account_id = %s AND ticker = %s''', (
                    value.xml_percent_of_nav,
                    value.user_id,
                    value.report_date,
                    value.account_id,
                    value.ticker,
                ))
                if cursor.rowcount != 1:
                    raise RuntimeError('A validated position row disappeared')

            for value in account_values:
                cursor.execute('''UPDATE accounts
                                  SET previous_net_liquidation = %s
                                  WHERE user_id = %s AND account_id = %s''', (
                    value.previous_net_liquidation,
                    value.user_id,
                    value.account_id,
                ))
                if cursor.rowcount != 1:
                    raise RuntimeError('A validated account row disappeared')

            for value in position_values:
                cursor.execute('''SELECT xml_percent_of_nav
                                  FROM positions
                                  WHERE user_id = %s AND date = %s
                                    AND account_id = %s AND ticker = %s''', (
                    value.user_id,
                    value.report_date,
                    value.account_id,
                    value.ticker,
                ))
                row = cursor.fetchone()
                if row is None or row['xml_percent_of_nav'] != value.xml_percent_of_nav:
                    raise RuntimeError('Position value verification failed')

            for value in account_values:
                cursor.execute('''SELECT previous_net_liquidation
                                  FROM accounts
                                  WHERE user_id = %s AND account_id = %s''', (
                    value.user_id,
                    value.account_id,
                ))
                row = cursor.fetchone()
                if (row is None or row['previous_net_liquidation'] !=
                        value.previous_net_liquidation):
                    raise RuntimeError('Account value verification failed')

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
        position_values, account_values, snapshot_count = prepare_values(
            conn,
            create_s3_client(),
            bucket,
        )
        write_and_verify(conn, position_values, account_values)
    finally:
        conn.close()

    print(
        'XML-native migration completed and verified: '
        f'{snapshot_count} snapshots, '
        f'{len(position_values)} positions, '
        f'{len(account_values)} current accounts.'
    )


if __name__ == '__main__':
    main()
