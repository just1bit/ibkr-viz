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


class ManualRefreshTests(unittest.TestCase):
    def setUp(self):
        backend_app.app.config['TESTING'] = True

    @mock.patch.object(backend_app.storage, 'set_user_manual_at')
    @mock.patch.object(backend_app.storage, 'get_user_by_id')
    @mock.patch.object(backend_app, 'get_db_g')
    @mock.patch.object(backend_app, 'fetch_and_store')
    def test_manual_refresh_forces_an_ibkr_fetch(
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


if __name__ == '__main__':
    unittest.main()
