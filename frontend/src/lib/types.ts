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

export interface Portfolio {
  date: string
  account_id: string
  accounts: string[]
  aliases: Record<string, string>
  holdings: Holding[]
  summary: PortfolioSummary
  equity: EquityComponents
  asset_class_summary: AllocationSlice[]
  ticker_summary: AllocationSlice[]
}

/** Map of ticker → target weight (percent of the portfolio). */
export type Targets = Record<string, number>

export interface Status {
  last_refresh: string
  /** flex_status from the API (replaces old 'mode' field) */
  flex_status: 'not_configured' | 'healthy' | 'error' | 'needs_attention'
  refresh_cooldown_remaining: number
}

export type DonutView = 'ticker' | 'asset_class'

/** Current authenticated user profile from GET /auth/me */
export interface UserProfile {
  user_id: string
  email: string
  name: string
  flex_query_id: string
  has_flex_query: boolean
  flex_status: 'not_configured' | 'healthy' | 'error' | 'needs_attention'
  is_admin: boolean
  created_at: string
  last_login: string
}

/** Result from POST /api/setup/test-flex */
export interface FlexTestResult {
  status: string
  accounts: Array<{ account_id: string; alias: string; account_type: string }>
  report_date: string
}

/** Result from POST /api/setup/configure */
export interface ConfigureResult {
  status: string
  flex_status: string
  has_flex_query: boolean
  report_date?: string
  fetch_error?: string
}
