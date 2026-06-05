"""IBKR Flex XML statement parser.

Parses real IBKR Flex XML responses into structured dictionaries for database
insertion.

  FlexQueryResponse
    └── FlexStatement (one per account)
          ├── AccountInformation          → account metadata, type
          ├── EquitySummaryInBase
          │     └── EquitySummaryByReportDateInBase  → NAV, cash, leverage
          ├── CashReport
          │     └── CashReportCurrency                → cash balances
          └── OpenPositions
                └── OpenPosition                      → holdings

Usage:
    data = parse_flex_xml(xml_text, date_str="2026-05-14")
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


def _asset_class(asset_cat: str, sub_cat: str) -> str:
    """Normalize IBKR assetCategory / subCategory into our asset class."""
    asset_cat = (asset_cat or 'STK').upper()
    if sub_cat == 'ETF':
        return 'ETF'
    if asset_cat == 'OPT':
        return 'OPTION'
    if asset_cat == 'STK':
        return 'STOCK'
    return CATEGORY_MAP.get(asset_cat, 'STOCK')


def _parse_mtm_holdings(stmt) -> list:
    """Fallback holdings source when OpenPositions is empty.

    Some Flex queries report positions only under MTMPerformanceSummaryInBase.
    Market value is reconstructed as closeQuantity x closePrice x multiplier,
    which reproduces the EquitySummary stock/options totals exactly. This
    section carries no cost basis, so unrealized P&L is left at zero.
    """
    container = stmt.find('MTMPerformanceSummaryInBase')
    if container is None:
        return []
    holdings = []
    for pos in container.iter('MTMPerformanceSummaryUnderlying'):
        symbol = pos.get('symbol', '')
        asset_cat = (pos.get('assetCategory', '') or '').upper()
        if not symbol or asset_cat in ('', 'CASH'):
            continue
        qty = float(pos.get('closeQuantity', 0) or 0)
        price = float(pos.get('closePrice', 0) or 0)
        multiplier = float(pos.get('multiplier', 1) or 1)
        if qty == 0:
            continue
        holdings.append({
            'ticker': symbol,
            'full_name': pos.get('description', ''),
            'asset_class': _asset_class(asset_cat, pos.get('subCategory', '')),
            'sector': 'Other',
            'quantity': abs(qty),
            'market_value': round(qty * price * multiplier, 2),
            'cost_price': 0.0,
            'currency': pos.get('currency', 'USD'),
        })
    return holdings


def parse_flex_xml(xml_text: str, date_str: str) -> Dict:
    """Parse a real IBKR Flex statement XML.

    Returns:
        {'date': str, 'accounts': [{
            'account_id': str,
            'account_type': 'MARGIN' | 'CASH',
            'net_liquidation': float,
            'cash_balance': float,
            'gross_pnl': float,
            'day_pnl': float,
            'leverage': float,
            'margin_util': float,
            'holdings': [{
                'ticker': str, 'full_name': str, 'asset_class': str,
                'sector': str, 'quantity': float, 'market_value': float,
                'cost_price': float, 'currency': str
            }]
        }]}
    """
    root = ET.fromstring(xml_text)
    accounts = []

    for stmt in root.iter('FlexStatement'):
        account_id = stmt.get('accountId', '')

        # --- Account type ---
        account_type = 'MARGIN'
        acc_info = stmt.find('AccountInformation')
        if acc_info is not None:
            caps = acc_info.get('accountCapabilities', 'MARGIN').upper()
            account_type = 'CASH' if caps == 'CASH' else 'MARGIN'

        # --- NAV from EquitySummaryInBase ---
        net_liq = 0.0
        gross_pos_value = 0.0
        es_by_date = {}
        es_container = stmt.find('EquitySummaryInBase')
        if es_container is not None:
            for es in es_container.iter('EquitySummaryByReportDateInBase'):
                rd = es.get('reportDate', '')
                es_by_date[rd] = {
                    'total': float(es.get('total', 0)),
                    'cash': float(es.get('cash', 0)),
                    'stock': float(es.get('stock', 0)),
                    'options': float(es.get('options', 0)),
                }
            if es_by_date:
                latest_rd = max(es_by_date.keys())
                latest_es = es_by_date[latest_rd]
                net_liq = latest_es['total']
                gross_pos_value = latest_es['stock'] + latest_es['options']

        # --- Cash balance ---
        cash_balance = 0.0
        cr_container = stmt.find('CashReport')
        if cr_container is not None:
            for crc in cr_container.iter('CashReportCurrency'):
                if crc.get('currency') == 'BASE_SUMMARY':
                    cash_balance = float(crc.get('endingSettledCash', 0))
                    break

        # --- Leverage ---
        leverage = 0.0
        if net_liq > 0 and gross_pos_value > 0:
            leverage = round(gross_pos_value / net_liq, 2)

        # --- PnL from multi-date equity summary ---
        day_pnl = 0.0
        gross_pnl = 0.0
        sorted_dates = sorted(es_by_date.keys())
        if len(sorted_dates) >= 2:
            day_pnl = round(
                es_by_date[sorted_dates[-1]]['total']
                - es_by_date[sorted_dates[-2]]['total'],
                2,
            )
        if len(sorted_dates) >= 1:
            first_total = es_by_date[sorted_dates[0]]['total']
            gross_pnl = round(net_liq - first_total, 2)

        # --- Holdings: prefer OpenPositions (has cost basis), else MTM ---
        holdings = []
        op_container = stmt.find('OpenPositions')
        if op_container is not None:
            for pos in op_container.iter('OpenPosition'):
                qty = abs(float(pos.get('position', 0)))
                mv = float(pos.get('positionValue', 0))
                cost_price = float(pos.get('costBasisPrice', 0))
                cost_money = float(pos.get('costBasisMoney', 0))
                if cost_price == 0 and qty > 0 and cost_money > 0:
                    cost_price = round(cost_money / qty, 4)

                holdings.append({
                    'ticker': pos.get('symbol', ''),
                    'full_name': pos.get('description', ''),
                    'asset_class': _asset_class(pos.get('assetCategory', 'STK'),
                                                pos.get('subCategory', '')),
                    'sector': 'Other',
                    'quantity': qty,
                    'market_value': mv,
                    'cost_price': cost_price,
                    'currency': pos.get('currency', 'USD'),
                })

        if not holdings:
            holdings = _parse_mtm_holdings(stmt)

        accounts.append({
            'account_id': account_id,
            'account_type': account_type,
            'net_liquidation': round(net_liq, 2),
            'cash_balance': round(cash_balance, 2),
            'gross_pnl': gross_pnl,
            'day_pnl': day_pnl,
            'leverage': leverage,
            'margin_util': 0.0,
            'holdings': holdings,
        })

    return {'date': date_str, 'accounts': accounts}
