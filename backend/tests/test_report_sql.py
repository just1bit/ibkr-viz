import pathlib
import sys
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import report_sql


class ReportSqlTests(unittest.TestCase):
    def test_position_insert_shape_is_kept_in_sync(self):
        holding = {
            'conid': '1',
            'ticker': 'TEST',
            'full_name': 'Test Holding',
            'asset_class': 'stock',
            'side': 'Long',
            'quantity': 1.0,
            'market_value': 2.0,
            'mark_price': 2.0,
            'cost_price': 1.0,
            'cost_basis': 1.0,
            'unrealized_pnl': 1.0,
            'day_pnl': 0.1,
            'prev_close_price': 1.9,
            'prev_close_quantity': 1.0,
            'xml_percent_of_nav': 10.0,
            'multiplier': 1.0,
            'strike': None,
            'expiry': '',
            'put_call': '',
            'underlying_symbol': '',
            'listing_exchange': 'NASDAQ',
            'currency': 'USD',
        }

        values = report_sql.position_values('u1', '2026-08-05', 'a1', holding)

        self.assertEqual(25, len(report_sql.POSITION_COLUMNS))
        self.assertEqual(len(report_sql.POSITION_COLUMNS), len(values))
        self.assertEqual(
            len(report_sql.POSITION_COLUMNS),
            report_sql.POSITION_INSERT_SQL.count('?'),
        )


if __name__ == '__main__':
    unittest.main()
