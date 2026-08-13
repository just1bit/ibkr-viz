import os
import pathlib
import sys
import unittest
from unittest import mock

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ['SCHEDULER_ENABLED'] = 'false'

import app as backend_app


class ExposureSummaryTests(unittest.TestCase):
    def test_cash_and_securities_follow_the_same_signed_exposure_rules(self):
        holdings = [
            {'ticker': 'LONG', 'market_value': 1200},
            {'ticker': 'SHORT', 'market_value': -450},
            backend_app.cash_holding(-150, 'U1'),
        ]

        result = backend_app.exposure_summary(holdings, 600)

        self.assertEqual(1200, result['long'])
        self.assertEqual(600, result['short'])
        self.assertEqual(1800, result['gross'])
        self.assertEqual(600, result['net'])
        self.assertEqual(3, result['gross_to_nav'])
        self.assertEqual(1, result['net_to_nav'])

    def test_cash_side_is_derived_from_balance_sign(self):
        self.assertEqual('LONG', backend_app.cash_holding(10, 'U1')['side'])
        self.assertEqual('SHORT', backend_app.cash_holding(-10, 'U1')['side'])

    def test_consolidated_cash_does_not_hide_cross_account_gross_exposure(self):
        positions = backend_app.cash_holdings_for_view(
            {'cash_balance': 20},
            {
                'U1': {'cash_balance': 100},
                'U2': {'cash_balance': -80},
            },
            'ALL',
        )

        result = backend_app.exposure_summary(positions, 20)

        self.assertEqual(100, result['long'])
        self.assertEqual(80, result['short'])
        self.assertEqual(180, result['gross'])
        self.assertEqual(20, result['net'])


class FakeConnection:
    def commit(self):
        return None


class FetchCursor:
    def execute(self, _query, _params=None):
        return None

    def fetchone(self):
        return {'latest': None}

    def fetchall(self):
        return []


class FetchConnection:
    def cursor(self):
        return FetchCursor()


class ManualRefreshTests(unittest.TestCase):
    def setUp(self):
        backend_app.app.config['TESTING'] = True

    @mock.patch.object(backend_app.threading, 'Thread')
    @mock.patch.object(backend_app.storage, 'create_refresh_job', return_value=42)
    @mock.patch.object(backend_app.storage, 'set_user_manual_at')
    @mock.patch.object(backend_app.storage, 'get_user_by_id')
    @mock.patch.object(backend_app, 'get_db_g')
    def test_manual_refresh_starts_an_async_job(
        self, get_db_g, get_user_by_id, set_manual_at, create_job, thread
    ):
        get_db_g.return_value = FakeConnection()
        get_user_by_id.return_value = {
            'last_manual_at': 0,
            'flex_status': 'healthy',
        }

        with backend_app.app.test_request_context('/api/trigger-refresh', method='POST'):
            backend_app.g.user_id = 'u1'
            response, status = backend_app.trigger_refresh.__wrapped__()

        self.assertEqual(202, status)
        self.assertEqual(42, response.get_json()['job_id'])
        set_manual_at.assert_called_once()
        create_job.assert_called_once_with(get_db_g.return_value, 'u1')
        thread.return_value.start.assert_called_once()

    @mock.patch.object(backend_app.storage, 'update_refresh_job')
    @mock.patch.object(backend_app, 'return_db')
    @mock.patch.object(backend_app, 'get_db', return_value=FakeConnection())
    @mock.patch.object(backend_app, 'fetch_and_store')
    def test_manual_refresh_job_records_the_real_failure(
        self, fetch_and_store, _get_db, _return_db, update_job
    ):
        fetch_and_store.return_value = (
            None, False, 'IBKR fetch failed: temporary failure', None
        )

        backend_app._run_manual_refresh_job('u1', 42)

        fetch_and_store.assert_called_once_with(
            'u1', force=True, trigger='manual'
        )
        self.assertEqual(
            mock.call(
                mock.ANY, 'u1', 42, 'refresh_error',
                'IBKR fetch failed: temporary failure', None,
            ),
            update_job.call_args_list[-1],
        )

    @mock.patch.object(backend_app.storage, 'get_refresh_job')
    @mock.patch.object(backend_app, 'get_db_g', return_value=FakeConnection())
    def test_manual_refresh_job_status_returns_completed_message(
        self, _get_db, get_job
    ):
        get_job.return_value = {
            'status': 'refresh_success',
            'report_date': '2026-08-07',
            'error_detail': 'New report stored: 2026-08-07',
        }

        with backend_app.app.test_request_context('/api/refresh-status/42'):
            backend_app.g.user_id = 'u1'
            response = backend_app.refresh_job_status.__wrapped__(42)

        self.assertEqual('success', response.get_json()['status'])
        self.assertEqual(
            'New report stored: 2026-08-07',
            response.get_json()['message'],
        )


class CacheWallTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            'date': '2026-08-05',
            'accounts': [{
                'account_id': 'U1',
                'alias': 'Main',
                'account_type': 'INDIVIDUAL',
            }],
        }

    @mock.patch.object(backend_app, '_store_parsed_data', return_value=None)
    @mock.patch.object(backend_app, '_write_cache')
    @mock.patch.object(backend_app.flex_parser, 'parse_flex_xml')
    @mock.patch.object(backend_app, '_read_cache', return_value=None)
    @mock.patch.object(backend_app.s3_store, 'get_raw_xml', return_value='<r2/>')
    def test_canonical_hit_restores_local_cache_and_stops(
        self, _get_raw_xml, read_cache, parse_xml, write_cache, _store
    ):
        parse_xml.return_value = self.data

        result = backend_app._recover_cached_report('u1', '2026-08-05')

        self.assertEqual(('2026-08-05', True, None), result[:3])
        write_cache.assert_called_once_with('u1', '<r2/>')
        read_cache.assert_called_once_with('u1')

    @mock.patch.object(backend_app, '_archive_xml_in_background')
    @mock.patch.object(backend_app, '_store_parsed_data', return_value=None)
    @mock.patch.object(backend_app.flex_parser, 'parse_flex_xml')
    @mock.patch.object(backend_app, '_read_cache', return_value='<local/>')
    @mock.patch.object(backend_app.s3_store, 'get_raw_xml', return_value=None)
    def test_local_hit_stores_before_scheduling_canonical_archive(
        self, _get_raw_xml, _read_cache, parse_xml, store_data, archive
    ):
        parse_xml.return_value = self.data
        calls = mock.Mock()
        calls.attach_mock(store_data, 'store')
        calls.attach_mock(archive, 'archive')

        result = backend_app._recover_cached_report('u1', '2026-08-05')

        self.assertEqual(('2026-08-05', True, None), result[:3])
        self.assertEqual(['store', 'archive'], [c[0] for c in calls.mock_calls])
        archive.assert_called_once_with(
            'u1', '2026-08-05', '<local/>', trigger='unknown'
        )
        _get_raw_xml.assert_not_called()

    @mock.patch.object(backend_app.flex_client, 'get_flex_xml')
    @mock.patch.object(backend_app, '_recover_cached_report')
    @mock.patch.object(backend_app.storage, 'decrypt_flex_token', return_value='token')
    @mock.patch.object(backend_app.storage, 'get_user_by_id')
    @mock.patch.object(backend_app, 'return_db')
    @mock.patch.object(backend_app, 'get_db', return_value=FetchConnection())
    def test_valid_cache_blocks_ibkr_for_automatic_and_forced_refresh(
        self, _get_db, _return_db, get_user, _decrypt, recover_cache, get_xml
    ):
        get_user.return_value = {
            'flex_token_enc': 'encrypted',
            'flex_query_id': 'query',
            'market_timezone': None,
            'last_fetch_at': backend_app.time.time(),
        }
        cached_result = ('2026-08-05', True, None, self.data['accounts'])
        recover_cache.return_value = cached_result

        for force in (False, True):
            with self.subTest(force=force):
                result = backend_app.fetch_and_store('u1', force=force)
                self.assertEqual(cached_result, result)

        self.assertEqual(2, recover_cache.call_count)
        get_xml.assert_not_called()

    @mock.patch.object(backend_app, '_store_parsed_data')
    @mock.patch.object(backend_app.flex_parser, 'parse_flex_xml')
    @mock.patch.object(backend_app, '_read_cache', return_value='<local/>')
    @mock.patch.object(backend_app.s3_store, 'get_raw_xml', return_value='<r2/>')
    def test_stale_cache_does_not_claim_to_satisfy_expected_date(
        self, _get_raw_xml, _read_cache, parse_xml, store_data
    ):
        parse_xml.return_value = {
            **self.data,
            'date': '2026-08-04',
        }

        result = backend_app._recover_cached_report('u1', '2026-08-05')

        self.assertIsNone(result)
        self.assertEqual(2, parse_xml.call_count)
        store_data.assert_not_called()


class RetryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.user = {
            'flex_token_enc': 'encrypted',
            'flex_query_id': 'query',
            'market_timezone': None,
            'last_fetch_at': backend_app.time.time(),
        }

    def test_exponential_backoff_tiers_are_one_two_four_eight_hours(self):
        with mock.patch.dict(backend_app.config, {
            'fetch_retry_backoff': 3600,
            'fetch_max_failures': 4,
        }):
            self.assertEqual(3600, backend_app._retry_backoff_seconds(1))
            self.assertEqual(7200, backend_app._retry_backoff_seconds(2))
            self.assertEqual(14400, backend_app._retry_backoff_seconds(3))
            self.assertEqual(28800, backend_app._retry_backoff_seconds(4))

    @mock.patch.object(backend_app.storage, 'set_user_flex_status')
    @mock.patch.object(backend_app.storage, 'count_consecutive_failures', return_value=4)
    @mock.patch.object(backend_app.storage, 'log_fetch_error')
    @mock.patch.object(backend_app, 'return_db')
    @mock.patch.object(backend_app, 'get_db', return_value=FakeConnection())
    def test_fourth_failure_changes_status_to_error(
        self, _get_db, _return_db, _log_error, _failure_count, set_status
    ):
        backend_app._safe_log_error(
            'u1', 'FLEX_1001', 'temporary failure',
            trigger='automatic', source='ibkr',
        )

        set_status.assert_called_once_with(
            mock.ANY, 'u1', 'error', commit=False
        )

    @mock.patch.object(backend_app.flex_client, 'get_flex_xml')
    @mock.patch.object(backend_app, '_recover_cached_report', return_value=None)
    @mock.patch.object(backend_app.storage, 'count_consecutive_failures', return_value=2)
    @mock.patch.object(backend_app.storage, 'decrypt_flex_token', return_value='token')
    @mock.patch.object(backend_app.storage, 'get_user_by_id')
    @mock.patch.object(backend_app, 'return_db')
    @mock.patch.object(backend_app, 'get_db', return_value=FetchConnection())
    def test_automatic_refresh_obeys_exponential_backoff(
        self, _get_db, _return_db, get_user, _decrypt, _failures,
        _recover_cache, get_xml
    ):
        get_user.return_value = self.user

        result = backend_app.fetch_and_store('u1')

        self.assertEqual((None, False, None, None), result)
        get_xml.assert_not_called()

    @mock.patch.object(backend_app.flex_client, 'get_flex_xml')
    @mock.patch.object(backend_app, '_recover_cached_report', return_value=None)
    @mock.patch.object(backend_app.storage, 'count_consecutive_failures', return_value=4)
    @mock.patch.object(backend_app.storage, 'decrypt_flex_token', return_value='token')
    @mock.patch.object(backend_app.storage, 'get_user_by_id')
    @mock.patch.object(backend_app, 'return_db')
    @mock.patch.object(backend_app, 'get_db', return_value=FetchConnection())
    def test_four_failures_stop_automatic_ibkr_requests(
        self, _get_db, _return_db, get_user, _decrypt, _failures,
        _recover_cache, get_xml
    ):
        get_user.return_value = self.user

        result = backend_app.fetch_and_store('u1')

        self.assertEqual((None, False, None, None), result)
        get_xml.assert_not_called()


if __name__ == '__main__':
    unittest.main()
