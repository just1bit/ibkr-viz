import pathlib
import sys
import unittest
from unittest import mock

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import flex_client


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


SEND_OK = """<FlexStatementResponse>
<Status>Success</Status><ReferenceCode>ref-1</ReferenceCode>
</FlexStatementResponse>"""


class FlexClientTests(unittest.TestCase):
    @mock.patch.object(flex_client.time, 'sleep')
    @mock.patch.object(flex_client.requests, 'get')
    def test_1001_is_retryable_not_a_credential_error(self, get, _sleep):
        get.side_effect = [
            FakeResponse(SEND_OK),
            FakeResponse("""<FlexStatementResponse><Status>Fail</Status>
                <ErrorCode>1001</ErrorCode>
                <ErrorMessage>Statement could not be generated.</ErrorMessage>
                </FlexStatementResponse>"""),
        ]

        with self.assertRaises(flex_client.FlexClientError) as raised:
            flex_client.get_flex_xml('token', 'query', max_wait=6)

        self.assertEqual('1001', raised.exception.error_code)
        self.assertTrue(raised.exception.retryable)
        self.assertFalse(raised.exception.needs_attention)

    @mock.patch.object(flex_client.requests, 'get')
    def test_expired_token_requires_attention(self, get):
        get.return_value = FakeResponse("""<FlexStatementResponse>
            <Status>Fail</Status><ErrorCode>1012</ErrorCode>
            <ErrorMessage>Token has expired.</ErrorMessage>
            </FlexStatementResponse>""")

        with self.assertRaises(flex_client.FlexClientError) as raised:
            flex_client.get_flex_xml('token', 'query')

        self.assertEqual('1012', raised.exception.error_code)
        self.assertTrue(raised.exception.needs_attention)
        self.assertFalse(raised.exception.retryable)

    @mock.patch.object(flex_client.time, 'sleep')
    @mock.patch.object(flex_client.requests, 'get')
    def test_generation_in_progress_is_polled_until_report_arrives(self, get, _sleep):
        pending = """<FlexStatementResponse><Status>Warn</Status>
            <ErrorCode>1019</ErrorCode>
            <ErrorMessage>Statement generation in progress.</ErrorMessage>
            </FlexStatementResponse>"""
        report = '<FlexQueryResponse><FlexStatements /></FlexQueryResponse>'
        get.side_effect = [FakeResponse(SEND_OK), FakeResponse(pending), FakeResponse(report)]

        xml = flex_client.get_flex_xml('token', 'query', max_wait=9)

        self.assertEqual(report, xml)
        self.assertEqual(3, get.call_count)


if __name__ == '__main__':
    unittest.main()
