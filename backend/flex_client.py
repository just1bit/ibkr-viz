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
    pass


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
        raise FlexClientError(f"SendRequest failed: {e}")

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        raise FlexClientError(f"SendRequest XML parse error: {e}")

    status = root.findtext('.//Status')
    if status in ('Error', 'Fail'):
        error_code = root.findtext('.//ErrorCode', '')
        error_msg = root.findtext('.//ErrorMessage', 'Unknown error')
        raise FlexClientError(f"Flex {status} {error_code}: {error_msg}")

    ref_code = root.findtext('.//ReferenceCode')
    if not ref_code:
        raise FlexClientError("No ReferenceCode found in SendRequest response")

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
            raise FlexClientError(f"GetStatement failed: {e}")

        text = resp.text.strip()
        if text.startswith('<?xml') or text.startswith('<FlexQueryResponse'):
            if save_path:
                os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(text)
            return text

    raise FlexClientError(f"Statement not ready after {max_wait}s")
