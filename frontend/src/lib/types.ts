export interface Account {
  account_id: string
  net_liquidation: number
  date: string
  day_pnl: number
  alias: string
  account_type: string
  syep: string
  drip: string
  tax_lot_method: string
  date_opened: string
}

export interface Holding {
  conid: string
  ticker: string
  full_name: string
  asset_class: string
  side: string
  quantity: number
  market_value: number
  mark_price: number | null
  cost_price: number | null
  cost_basis: number | null
  unrealized_pnl: number
  day_pnl: number
  prev_close_price: number | null
  prev_close_quantity: number | null
  multiplier: number | null
  strike: number | null
  expiry: string
  put_call: string
  underlying_symbol: string
  listing_exchange: string
  currency: string
  account_id: string
}

export interface AllocationSlice {
  name: string
  value: number
  /** Assigned on the client (see AllocationCard); absent in the API response. */
  color?: string
  full_name?: string
  day_pnl?: number
}

export interface PortfolioSummary {
  total_value: number
  net_liquidation: number
  total_cash: number
  total_day_pnl: number
}

/** NAV decomposition straight from EquitySummaryInBase. */
export interface EquityComponents {
  stock: number
  options: number
  cash: number
  dividend_accruals: number
  interest_accruals: number
  total: number
}

/** MTD/YTD income & costs straight from CashReport (BASE_SUMMARY). */
export interface CashReport {
  commissions_mtd: number
  commissions_ytd: number
  broker_interest_mtd: number
  broker_interest_ytd: number
  dividends_mtd: number
  dividends_ytd: number
  payment_in_lieu_mtd: number
  payment_in_lieu_ytd: number
  withholding_tax_mtd: number
  withholding_tax_ytd: number
  deposit_withdrawals_mtd: number
  deposit_withdrawals_ytd: number
  net_trades_sales_mtd: number
  net_trades_sales_ytd: number
  net_trades_purchases_mtd: number
  net_trades_purchases_ytd: number
}

export interface Portfolio {
  date: string
  account_id: string
  accounts: string[]
  aliases: Record<string, string>
  holdings: Holding[]
  summary: PortfolioSummary
  equity: EquityComponents
  cash_report: CashReport
  asset_class_summary: AllocationSlice[]
  ticker_summary: AllocationSlice[]
}

/** Map of ticker → target weight (percent of the portfolio). */
export type Targets = Record<string, number>

export interface Status {
  last_refresh: string
  mode: 'mock' | 'live'
  refresh_cooldown_remaining: number
}

export type DonutView = 'ticker' | 'asset_class'
