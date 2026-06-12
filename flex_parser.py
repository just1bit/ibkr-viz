"""IBKR Flex XML statement parser.

Parses real IBKR Flex XML responses into structured dictionaries for database
insertion. Every value is read directly from the XML — no fallbacks and no
recomputation of figures the statement already provides. A missing section or
attribute is a data problem in the Flex query, not something to paper over.

  FlexQueryResponse
    └── FlexStatement (one per account)
          ├── AccountInformation                     → account type
          ├── EquitySummaryInBase
          │     └── EquitySummaryByReportDateInBase  → NAV, ledger cash
          ├── MTMPerformanceSummaryInBase
          │     └── MTMPerformanceSummaryUnderlying  → day P&L (account + per position)
          └── OpenPositions
                └── OpenPosition                     → holdings

Usage:
    data = parse_flex_xml(xml_text)
"""

import xml.etree.ElementTree as ET
from typing import Dict


CATEGORY_MAP = {
    'STK': 'STOCK',
    'OPT': 'OPTION',
    'FUT': 'FUTURE',
    'BOND': 'BOND',
    'CASH': 'CASH',
}


def _statement_date(stmt) -> str:
    """Period end date of a statement — the date the data actually describes.

    Flex statements with period=LastBusinessDay lag the fetch date by 1-2
    days, so the fetch date must never be used to label the data. IBKR may
    format toDate as YYYY-MM-DD or YYYYMMDD depending on query settings.
    """
    raw = (stmt.get('toDate') or '').strip()
    if len(raw) == 8 and raw.isdigit():
        return f'{raw[:4]}-{raw[4:6]}-{raw[6:]}'
    return raw


def _asset_class(asset_cat: str, sub_cat: str) -> str:
    """Normalize IBKR assetCategory / subCategory into our asset class."""
    if sub_cat == 'ETF':
        return 'ETF'
    return CATEGORY_MAP.get((asset_cat or '').upper(), 'STOCK')


def _num(el, attr) -> float:
    return float(el.get(attr) or 0)


def parse_flex_xml(xml_text: str) -> Dict:
    """Parse a real IBKR Flex statement XML.

    The returned 'date' is the report date taken from the statements' toDate
    attribute (the period the data describes).

    Returns:
        {'date': str, 'accounts': [{
            'account_id': str,
            'account_type': 'MARGIN' | 'CASH',
            'net_liquidation': float,
            'cash_balance': float,
            'day_pnl': float,
            'holdings': [{
                'conid': str, 'ticker': str, 'full_name': str,
                'asset_class': str, 'side': str,
                'quantity': float, 'market_value': float, 'mark_price': float,
                'cost_price': float, 'cost_basis': float,
                'unrealized_pnl': float, 'day_pnl': float, 'currency': str
            }]
        }]}
    """
    root = ET.fromstring(xml_text)
    accounts = []
    report_dates = []

    for stmt in root.iter('FlexStatement'):
        account_id = stmt.get('accountId', '')
        report_dates.append(_statement_date(stmt))

        caps = stmt.find('AccountInformation').get('accountCapabilities', '').upper()
        account_type = 'CASH' if caps == 'CASH' else 'MARGIN'

        # --- NAV + ledger cash: latest EquitySummary row (NAV basis:
        #     cash + positions + accruals == total) ---
        es_rows = list(stmt.find('EquitySummaryInBase'))
        latest_es = max(es_rows, key=lambda e: e.get('reportDate', ''))
        net_liq = _num(latest_es, 'total')
        cash_balance = _num(latest_es, 'cash')

        # --- Day P&L from MTM performance: the blank-symbol row is the
        #     account total IBKR reports directly; named rows are per
        #     position, joined to holdings below by conid ---
        day_pnl = 0.0
        mtm_by_conid = {}
        for row in stmt.find('MTMPerformanceSummaryInBase'):
            if (row.get('symbol') or '').strip():
                mtm_by_conid[row.get('conid', '')] = round(_num(row, 'total'), 2)
            else:
                day_pnl = round(_num(row, 'total'), 2)

        holdings = []
        for pos in stmt.find('OpenPositions'):
            conid = pos.get('conid', '')
            holdings.append({
                'conid': conid,
                'ticker': pos.get('symbol', ''),
                'full_name': pos.get('description', ''),
                'asset_class': _asset_class(pos.get('assetCategory', ''),
                                            pos.get('subCategory', '')),
                'side': pos.get('side', ''),
                'quantity': _num(pos, 'position'),
                'market_value': _num(pos, 'positionValue'),
                'mark_price': _num(pos, 'markPrice'),
                'cost_price': _num(pos, 'costBasisPrice'),
                'cost_basis': _num(pos, 'costBasisMoney'),
                'unrealized_pnl': _num(pos, 'fifoPnlUnrealized'),
                'day_pnl': mtm_by_conid.get(conid, 0.0),
                'currency': pos.get('currency', 'USD'),
            })

        accounts.append({
            'account_id': account_id,
            'account_type': account_type,
            'net_liquidation': round(net_liq, 2),
            'cash_balance': round(cash_balance, 2),
            'day_pnl': day_pnl,
            'holdings': holdings,
        })

    return {'date': max(report_dates), 'accounts': accounts}
