import os
import pathlib
import sys
import unittest
from unittest import mock

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ['SCHEDULER_ENABLED'] = 'false'

import app as backend_app


class FakeConnection:
    def commit(self):
        return None


class FetchCursor:
    def execute(self, _query, _params=None):
        return None

    def fetchone(self):
        return {'latest': None}


class FetchConnection:
    def cursor(self):
        return FetchCursor()


class ManualRefreshTests(unittest.TestCase):
    def setUp(self):
        backend_app.app.config['TESTING'] = True

    @mock.patch.object(backend_app.storage, 'set_user_manual_at')
    @mock.patch.object(backend_app.storage, 'get_user_by_id')
    @mock.patch.object(backend_app, 'get_db_g')
    @mock.patch.object(backend_app, 'fetch_and_store')
    def test_manual_refresh_forces_the_refresh_pipeline(
        self, fetch_and_store, get_db_g, get_user_by_id, set_manual_at
    ):
        get_db_g.return_value = FakeConnection()
        get_user_by_id.return_value = {
            'last_manual_at': 0,
            'flex_status': 'healthy',
        }
        fetch_and_store.return_value = ('2026-08-05', True, None, [])

        with backend_app.app.test_request_context('/api/trigger-refresh', method='POST'):
            backend_app.g.user_id = 'u1'
            response = backend_app.trigger_refresh.__wrapped__()

        fetch_and_store.assert_called_once_with('u1', force=True)
        set_manual_at.assert_called_once()
        self.assertEqual('New report stored: 2026-08-05', response.get_json()['message'])

    @mock.patch.object(backend_app.storage, 'set_user_manual_at')
    @mock.patch.object(backend_app.storage, 'get_user_by_id')
    @mock.patch.object(backend_app, 'get_db_g')
    @mock.patch.object(backend_app, 'fetch_and_store')
    def test_manual_refresh_returns_the_real_failure(
        self, fetch_and_store, get_db_g, get_user_by_id, _set_manual_at
    ):
        get_db_g.return_value = FakeConnection()
        get_user_by_id.side_effect = [
            {'last_manual_at': 0, 'flex_status': 'healthy'},
            {'last_manual_at': 0, 'flex_status': 'error'},
        ]
        fetch_and_store.return_value = (
            None, False, 'IBKR fetch failed: temporary failure', None
        )

        with backend_app.app.test_request_context('/api/trigger-refresh', method='POST'):
            backend_app.g.user_id = 'u1'
            response, status = backend_app.trigger_refresh.__wrapped__()

        self.assertEqual(502, status)
        self.assertEqual(
            'IBKR fetch failed: temporary failure', response.get_json()['error']
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
    @mock.patch.object(backend_app, '_read_cache')
    @mock.patch.object(backend_app.s3_store, 'get_raw_xml', return_value='<r2/>')
    def test_canonical_hit_restores_local_cache_and_stops(
        self, _get_raw_xml, read_cache, parse_xml, write_cache, _store
    ):
        parse_xml.return_value = self.data

        result = backend_app._recover_cached_report('u1', '2026-08-05')

        self.assertEqual(('2026-08-05', True, None), result[:3])
        write_cache.assert_called_once_with('u1', '<r2/>')
        read_cache.assert_not_called()

    @mock.patch.object(backend_app, '_store_parsed_data', return_value=None)
    @mock.patch.object(backend_app.s3_store, 'save_raw_xml')
    @mock.patch.object(backend_app.flex_parser, 'parse_flex_xml')
    @mock.patch.object(backend_app, '_read_cache', return_value='<local/>')
    @mock.patch.object(backend_app.s3_store, 'get_raw_xml', return_value=None)
    def test_local_hit_restores_canonical_archive(
        self, _get_raw_xml, _read_cache, parse_xml, save_raw_xml, _store
    ):
        parse_xml.return_value = self.data

        result = backend_app._recover_cached_report('u1', '2026-08-05')

        self.assertEqual(('2026-08-05', True, None), result[:3])
        save_raw_xml.assert_called_once_with('u1', '2026-08-05', '<local/>')

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


if __name__ == '__main__':
    unittest.main()
