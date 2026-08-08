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
    def __init__(self, result=None, error=None, head_error=None):
        self.result = result
        self.error = error
        self.head_error = head_error
        self.put_calls = []

    def get_object(self, **_kwargs):
        if self.error:
            raise self.error
        return {'Body': io.BytesIO(self.result.encode('utf-8'))}

    def head_object(self, **_kwargs):
        if self.head_error:
            raise self.head_error
        return {}

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)


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


class S3WriteTests(unittest.TestCase):
    def test_existing_canonical_xml_is_not_uploaded_again(self):
        client = FakeS3Client()
        store = make_store(client)

        key, created = store.save_raw_xml_if_absent(
            'u1', '2026-08-05', '<xml/>'
        )

        self.assertEqual('flex_raw/u1/2026-08-05.xml', key)
        self.assertFalse(created)
        self.assertEqual([], client.put_calls)

    def test_missing_canonical_xml_is_uploaded_once(self):
        client = FakeS3Client(
            head_error=FakeS3Error('NoSuchKey', 404)
        )
        store = make_store(client)

        _key, created = store.save_raw_xml_if_absent(
            'u1', '2026-08-05', '<xml/>'
        )

        self.assertTrue(created)
        self.assertEqual(1, len(client.put_calls))


class SchedulerEligibilityTests(unittest.TestCase):
    def test_only_healthy_users_are_automatically_scheduled(self):
        conn = CaptureConnection()

        storage.get_active_users_with_credentials(conn)

        normalized = ' '.join(conn.c.query.split())
        self.assertIn("flex_status = 'healthy'", normalized)
        self.assertNotIn("'error'", normalized)


if __name__ == '__main__':
    unittest.main()
