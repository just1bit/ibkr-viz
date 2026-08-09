import pathlib
import sys
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import flex_parser


FLEX_XML = """<FlexQueryResponse><FlexStatements>
<FlexStatement accountId="U1" toDate="20260805">
  <AccountInformation accountCapabilities="MARGIN" />
  <EquitySummaryInBase>
    <EquitySummaryByReportDateInBase reportDate="2026-08-04" total="1000" />
    <EquitySummaryByReportDateInBase reportDate="2026-08-05" total="1015" />
  </EquitySummaryInBase>
  <MTMPerformanceSummaryInBase>
    <MTMPerformanceSummaryUnderlying symbol="" total="15" />
    <MTMPerformanceSummaryUnderlying conid="1" symbol="OPEN" description="Open position"
      assetCategory="STK" currency="USD" total="10" prevClosePrice="100"
      prevCloseQuantity="1" />
    <MTMPerformanceSummaryUnderlying conid="2" symbol="CLOSED" description="Closed intraday"
      assetCategory="STK" currency="USD" total="5" prevClosePrice="50"
      prevCloseQuantity="0" />
    <MTMPerformanceSummaryUnderlying conid="3" symbol="ZERO" description="No contribution"
      assetCategory="STK" currency="USD" total="0" prevClosePrice="20"
      prevCloseQuantity="1" />
  </MTMPerformanceSummaryInBase>
  <OpenPositions>
    <OpenPosition conid="1" symbol="OPEN" description="Open position"
      assetCategory="STK" position="1" positionValue="110" markPrice="110"
      currency="USD" />
  </OpenPositions>
</FlexStatement></FlexStatements></FlexQueryResponse>"""


class FlexParserTests(unittest.TestCase):
    def test_keeps_closed_intraday_instrument_as_daily_pnl_contribution(self):
        account = flex_parser.parse_flex_xml(FLEX_XML)['accounts'][0]

        self.assertEqual(['OPEN'], [h['ticker'] for h in account['holdings']])
        self.assertEqual(
            ['OPEN', 'CLOSED'],
            [c['ticker'] for c in account['day_pnl_contributions']],
        )
        self.assertEqual(10, account['holdings'][0]['day_pnl'])
        self.assertEqual(15, account['day_pnl'])

    def test_filters_zero_rows_and_contributions_sum_to_authoritative_total(self):
        data = flex_parser.parse_flex_xml(FLEX_XML)

        authoritative_total = round(
            sum(account['day_pnl'] for account in data['accounts']), 2
        )
        contribution_total = round(sum(
            contribution['day_pnl']
            for account in data['accounts']
            for contribution in account['day_pnl_contributions']
        ), 2)

        self.assertNotIn(
            'ZERO',
            [
                contribution['ticker']
                for account in data['accounts']
                for contribution in account['day_pnl_contributions']
            ],
        )
        self.assertEqual(authoritative_total, contribution_total)

    def test_negative_cash_is_persisted_as_short_cash_position(self):
        xml = FLEX_XML.replace(
            'reportDate="2026-08-05" total="1015"',
            'reportDate="2026-08-05" total="1015" cash="-250.25"',
        )

        account = flex_parser.parse_flex_xml(xml)['accounts'][0]
        cash = next(h for h in account['holdings'] if h['ticker'] == 'CASH')

        self.assertEqual(-250.25, account['cash_balance'])
        self.assertEqual(-250.25, cash['market_value'])
        self.assertEqual('SHORT', cash['side'])

    def test_cash_only_report_still_has_a_position_snapshot(self):
        xml = FLEX_XML.replace(
            'reportDate="2026-08-05" total="1015"',
            'reportDate="2026-08-05" total="1015" cash="500"',
        )
        start = xml.index('  <OpenPositions>')
        end = xml.index('  </OpenPositions>') + len('  </OpenPositions>')
        xml = xml[:start] + '  <OpenPositions />' + xml[end:]

        holdings = flex_parser.parse_flex_xml(xml)['accounts'][0]['holdings']

        self.assertEqual(['CASH'], [h['ticker'] for h in holdings])
        self.assertEqual(500, holdings[0]['market_value'])


if __name__ == '__main__':
    unittest.main()
