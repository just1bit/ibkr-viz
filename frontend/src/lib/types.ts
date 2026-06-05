export interface Account {
  account_id: string
  net_liquidation: number
  date: string
  gross_pnl: number
  day_pnl: number
  leverage: number
  margin_util: number
  account_type: string
}

export interface Holding {
  ticker: string
  full_name: string
  asset_class: string
  sector: string
  quantity: number
  market_value: number
  cost_price: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  currency: string
  account_id: string
  weight: number
}

export interface AllocationSlice {
  name: string
  value: number
  pct: number
  /** Assigned on the client (see AllocationCard); absent in the API response. */
  color?: string
  full_name?: string
  asset_class?: string
}

export interface PortfolioSummary {
  total_value: number
  allocation_total: number
  net_liquidation: number
  total_cash: number
  total_day_pnl: number
  total_gross_pnl: number
  cash_gap: number
}

export interface Portfolio {
  date: string
  account_id: string
  accounts: string[]
  holdings: Holding[]
  summary: PortfolioSummary
  asset_class_summary: AllocationSlice[]
  sector_summary: AllocationSlice[]
  ticker_summary: AllocationSlice[]
}

/** Map of ticker → target weight (percent of the portfolio). */
export type Targets = Record<string, number>

export interface Margin {
  account_id: string
  leverage: number
  margin_util: number
  is_cash_account: boolean
  color_margin: 'green' | 'yellow' | 'red'
}

export interface Status {
  last_refresh: string
  mode: 'mock' | 'live'
  refresh_cooldown_remaining: number
}

export type DonutView = 'ticker' | 'sector' | 'asset_class'
