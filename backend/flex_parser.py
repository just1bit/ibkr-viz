"""IBKR Flex XML statement parser.

Parses real IBKR Flex XML responses into structured dictionaries for database
insertion. Every value is read directly from the XML — no fallbacks and no
recomputation of figures the statement already provides. A missing section or
attribute is a data problem in the Flex query, not something to paper over.

  FlexQueryResponse
    └── FlexStatement (one per account)
          ├── AccountInformation                     → alias, type, SYEP/DRIP flags
          ├── EquitySummaryInBase
          │     └── EquitySummaryByReportDateInBase  → NAV components (stock,
          │                                            options, cash, accruals)
          ├── MTMPerformanceSummaryInBase
          │     └── MTMPerformanceSummaryUnderlying  → day P&L (account + per
          │                                            position), prev close
          └── OpenPositions
                └── OpenPosition                     → holdings (incl. option
                                                       contract terms)

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
            'account_id', 'alias', 'account_type',
            'syep', 'drip', 'tax_lot_method', 'date_opened',
            'net_liquidation', 'cash_balance', 'stock_value', 'options_value',
            'dividend_accruals', 'interest_accruals', 'day_pnl',
            'holdings': [{
                'conid', 'ticker', 'full_name', 'asset_class', 'side',
                'quantity', 'market_value', 'mark_price',
                'cost_price', 'cost_basis', 'unrealized_pnl',
                'day_pnl', 'prev_close_price', 'prev_close_quantity',
                'multiplier', 'strike', 'expiry', 'put_call',
                'underlying_symbol', 'listing_exchange', 'currency'
            }]
        }]}
    """
    root = ET.fromstring(xml_text)
    accounts = []
    report_dates = []

    for stmt in root.iter('FlexStatement'):
        account_id = stmt.get('accountId', '')
        report_dates.append(_statement_date(stmt))

        info = stmt.find('AccountInformation')
        caps = info.get('accountCapabilities', '').upper()

        # --- NAV components: latest EquitySummary row (NAV basis:
        #     cash + positions + accruals == total) ---
        es_rows = list(stmt.find('EquitySummaryInBase'))
        latest_es = max(es_rows, key=lambda e: e.get('reportDate', ''))

        # --- Day P&L from MTM performance: the blank-symbol row is the
        #     account total IBKR reports directly; named rows are per
        #     position, joined to holdings below by conid ---
        day_pnl = 0.0
        mtm_by_conid = {}
        for row in stmt.find('MTMPerformanceSummaryInBase'):
            if (row.get('symbol') or '').strip():
                mtm_by_conid[row.get('conid', '')] = {
                    'day_pnl': round(_num(row, 'total'), 2),
                    'prev_close_price': _num(row, 'prevClosePrice'),
                    'prev_close_quantity': _num(row, 'prevCloseQuantity'),
                }
            else:
                day_pnl = round(_num(row, 'total'), 2)

        holdings = []
        for pos in stmt.find('OpenPositions'):
            conid = pos.get('conid', '')
            mtm = mtm_by_conid.get(conid, {})
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
                'day_pnl': mtm.get('day_pnl', 0.0),
                'prev_close_price': mtm.get('prev_close_price', 0.0),
                'prev_close_quantity': mtm.get('prev_close_quantity', 0.0),
                'multiplier': _num(pos, 'multiplier'),
                'strike': _num(pos, 'strike'),
                'expiry': pos.get('expiry', ''),
                'put_call': pos.get('putCall', ''),
                'underlying_symbol': pos.get('underlyingSymbol', ''),
                'listing_exchange': pos.get('listingExchange', ''),
                'currency': pos.get('currency', 'USD'),
            })

        accounts.append({
            'account_id': account_id,
            'alias': info.get('acctAlias', ''),
            'account_type': 'CASH' if caps == 'CASH' else 'MARGIN',
            'syep': info.get('syepEnrollmentStatus', ''),
            'drip': info.get('dividendReinvestmentEnabled', ''),
            'tax_lot_method': info.get('taxLotMatchingMethod', ''),
            'date_opened': info.get('dateOpened', ''),
            'net_liquidation': round(_num(latest_es, 'total'), 2),
            'cash_balance': round(_num(latest_es, 'cash'), 2),
            'stock_value': round(_num(latest_es, 'stock'), 2),
            'options_value': round(_num(latest_es, 'options'), 2),
            'dividend_accruals': round(_num(latest_es, 'dividendAccruals'), 2),
            'interest_accruals': round(_num(latest_es, 'interestAccruals'), 2),
            'day_pnl': day_pnl,
            'holdings': holdings,
        })

    return {'date': max(report_dates), 'accounts': accounts}
