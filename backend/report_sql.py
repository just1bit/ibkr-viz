"""SQL and value mapping for portfolio position snapshots."""

POSITION_COLUMNS = (
    'user_id',
    'date',
    'account_id',
    'conid',
    'ticker',
    'full_name',
    'asset_class',
    'side',
    'quantity',
    'market_value',
    'mark_price',
    'cost_price',
    'cost_basis',
    'unrealized_pnl',
    'day_pnl',
    'prev_close_price',
    'prev_close_quantity',
    'xml_percent_of_nav',
    'multiplier',
    'strike',
    'expiry',
    'put_call',
    'underlying_symbol',
    'listing_exchange',
    'currency',
)

POSITION_INSERT_SQL = (
    f"INSERT INTO positions ({', '.join(POSITION_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in POSITION_COLUMNS)})"
)

DAILY_PNL_CONTRIBUTION_COLUMNS = (
    'user_id',
    'date',
    'account_id',
    'conid',
    'ticker',
    'full_name',
    'asset_class',
    'day_pnl',
    'prev_close_price',
    'prev_close_quantity',
    'currency',
)

DAILY_PNL_CONTRIBUTION_INSERT_SQL = (
    'INSERT INTO daily_pnl_contributions '
    f"({', '.join(DAILY_PNL_CONTRIBUTION_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in DAILY_PNL_CONTRIBUTION_COLUMNS)})"
)


def position_values(user_id, report_date, account_id, holding):
    """Return values in exactly the same order as POSITION_COLUMNS."""
    return (
        user_id,
        report_date,
        account_id,
        holding['conid'],
        holding['ticker'],
        holding['full_name'],
        holding['asset_class'],
        holding['side'],
        holding['quantity'],
        holding['market_value'],
        holding['mark_price'],
        holding['cost_price'],
        holding['cost_basis'],
        holding['unrealized_pnl'],
        holding['day_pnl'],
        holding['prev_close_price'],
        holding['prev_close_quantity'],
        holding.get('xml_percent_of_nav'),
        holding['multiplier'],
        holding['strike'],
        holding['expiry'],
        holding['put_call'],
        holding['underlying_symbol'],
        holding['listing_exchange'],
        holding['currency'],
    )


def daily_pnl_contribution_values(user_id, report_date, account_id,
                                  contribution):
    """Return values in DAILY_PNL_CONTRIBUTION_COLUMNS order."""
    return (
        user_id,
        report_date,
        account_id,
        contribution['conid'],
        contribution['ticker'],
        contribution['full_name'],
        contribution['asset_class'],
        contribution['day_pnl'],
        contribution['prev_close_price'],
        contribution['prev_close_quantity'],
        contribution['currency'],
    )
