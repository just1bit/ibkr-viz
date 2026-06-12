export interface Account {
  account_id: string
  net_liquidation: number
  date: string
  day_pnl: number
  account_type: string
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

export interface Portfolio {
  date: string
  account_id: string
  accounts: string[]
  holdings: Holding[]
  summary: PortfolioSummary
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
