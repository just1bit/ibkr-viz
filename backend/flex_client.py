"""IBKR Flex Web Service HTTP client.

Handles the two-step Flex request flow:
  1. SendRequest  → get reference code
  2. GetStatement → poll until statement XML is ready, save locally, then return

Critical: XML is written to local disk the instant it arrives from IBKR, before
the caller does anything else. This prevents data loss if subsequent steps fail.

Usage:
    xml_text = get_flex_xml(token="...", query_id="...", save_path="/tmp/flex.xml")
"""

import os
import time
from typing import Optional

import requests
import xml.etree.ElementTree as ET

FLEX_REQUEST_URL = "https://ndcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
FLEX_STATEMENT_URL = "https://ndcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"


class FlexClientError(Exception):
    """A structured IBKR Flex failure."""

    CREDENTIAL_ERROR_CODES = {
        '1010',  # legacy query
        '1011',  # service account inactive
        '1012',  # token expired
        '1013',  # IP restriction
        '1014',  # invalid query
        '1015',  # invalid token
        '1016',  # invalid account
    }
    RETRYABLE_ERROR_CODES = {
        '1001', '1003', '1004', '1005', '1006', '1007', '1008', '1009',
        '1017', '1018', '1019', '1021',
    }

    def __init__(self, message, *, error_code=None, status=None, stage=None):
        super().__init__(message)
        self.error_code = str(error_code) if error_code else None
        self.status = status
        self.stage = stage

    @property
    def needs_attention(self):
        return self.error_code in self.CREDENTIAL_ERROR_CODES

    @property
    def retryable(self):
        return self.error_code is None or self.error_code in self.RETRYABLE_ERROR_CODES


def _response_error(root, stage):
    status = root.findtext('.//Status')
    if status not in ('Error', 'Fail', 'Warn'):
        return None
    error_code = root.findtext('.//ErrorCode', '')
    error_msg = root.findtext('.//ErrorMessage', 'Unknown error')
    return FlexClientError(
        f"Flex {status} {error_code}: {error_msg}",
        error_code=error_code,
        status=status,
        stage=stage,
    )


def get_flex_xml(
    token: str,
    query_id: str,
    max_wait: int = 30,
    save_path: Optional[str] = None,
) -> str:
    """Fetch Flex statement XML and optionally save to local file immediately.

    The local save happens INSIDE the polling loop the moment a valid XML
    response arrives — before this function returns. This guarantees the raw
    data is on disk even if the caller crashes afterward.

    Args:
        token: IBKR Flex Web Service token
        query_id: Flex Query ID
        max_wait: Maximum seconds to poll for statement readiness
        save_path: If set, write raw XML to this path before returning

    Returns:
        Raw XML string of the statement

    Raises:
        FlexClientError: On any HTTP or parsing error
    """
    # Step 1: Send request
    params = {'t': token, 'q': query_id, 'v': '3'}
    try:
        resp = requests.get(FLEX_REQUEST_URL, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise FlexClientError(f"SendRequest failed: {e}", stage='send_request')

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        raise FlexClientError(
            f"SendRequest XML parse error: {e}", stage='send_request'
        )

    response_error = _response_error(root, 'send_request')
    if response_error:
        raise response_error

    ref_code = root.findtext('.//ReferenceCode')
    if not ref_code:
        raise FlexClientError(
            "No ReferenceCode found in SendRequest response",
            stage='send_request',
        )

    # Step 2: Poll for statement
    poll_interval = 3
    waited = 0

    while waited < max_wait:
        time.sleep(poll_interval)
        waited += poll_interval

        try:
            resp = requests.get(FLEX_STATEMENT_URL, params={
                't': token, 'q': ref_code, 'v': '3'
            }, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise FlexClientError(f"GetStatement failed: {e}", stage='get_statement')

        text = resp.text.strip()
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            continue

        tag = root.tag.rsplit('}', 1)[-1]
        if tag == 'FlexQueryResponse':
            if save_path:
                os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(text)
            return text

        response_error = _response_error(root, 'get_statement')
        if response_error:
            if response_error.error_code == '1019':
                continue
            raise response_error

    raise FlexClientError(
        f"Statement not ready after {max_wait}s", stage='get_statement'
    )
