import io
import pathlib
import sys
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import storage


class FakeS3Error(Exception):
    def __init__(self, code, status):
        super().__init__(f'S3 error {code}')
        self.response = {
            'Error': {'Code': code},
            'ResponseMetadata': {'HTTPStatusCode': status},
        }


class FakeS3Client:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def get_object(self, **_kwargs):
        if self.error:
            raise self.error
        return {'Body': io.BytesIO(self.result.encode('utf-8'))}


class CaptureCursor:
    def execute(self, query, _params=None):
        self.query = query

    def fetchall(self):
        return []


class CaptureConnection:
    def __init__(self):
        self.c = CaptureCursor()

    def cursor(self):
        return self.c


def make_store(client):
    store = object.__new__(storage.S3Store)
    store.enabled = True
    store.client = client
    store.bucket = 'bucket'
    store.prefix = 'flex_raw/'
    return store


class S3ReadTests(unittest.TestCase):
    def test_not_found_is_a_normal_cache_miss(self):
        store = make_store(FakeS3Client(error=FakeS3Error('NoSuchKey', 404)))

        self.assertIsNone(store.get_raw_xml('u1', '2026-08-05'))

    def test_non_404_failure_is_not_silently_treated_as_a_miss(self):
        store = make_store(FakeS3Client(error=FakeS3Error('AccessDenied', 403)))

        with self.assertRaises(storage.ObjectStoreReadError):
            store.get_raw_xml('u1', '2026-08-05')

    def test_success_returns_decoded_xml(self):
        store = make_store(FakeS3Client(result='<xml/>'))

        self.assertEqual(
            '<xml/>', store.get_raw_xml('u1', '2026-08-05')
        )


class SchedulerEligibilityTests(unittest.TestCase):
    def test_only_healthy_users_are_automatically_scheduled(self):
        conn = CaptureConnection()

        storage.get_active_users_with_credentials(conn)

        normalized = ' '.join(conn.c.query.split())
        self.assertIn("flex_status = 'healthy'", normalized)
        self.assertNotIn("'error'", normalized)


if __name__ == '__main__':
    unittest.main()
