import { useState } from 'react'
import type { CashReport, Portfolio } from '../lib/types'
import { fmtUSDFull } from '../lib/format'
import { Segmented } from './Segmented'

interface Props {
  portfolio: Portfolio
  hidden: boolean
}

type Period = 'mtd' | 'ytd'

const PERIODS: { value: Period; label: string }[] = [
  { value: 'mtd', label: 'MTD' },
  { value: 'ytd', label: 'YTD' },
]

interface Item {
  label: string
  /** CashReport field name without its `_mtd` / `_ytd` suffix. */
  key: string
}

const GROUPS: { title: string; items: Item[] }[] = [
  {
    title: 'Income',
    items: [
      { label: 'Dividends', key: 'dividends' },
      { label: 'Payment in lieu', key: 'payment_in_lieu' },
      { label: 'Withholding tax', key: 'withholding_tax' },
    ],
  },
  {
    title: 'Costs',
    items: [
      { label: 'Commissions', key: 'commissions' },
      { label: 'Margin interest', key: 'broker_interest' },
    ],
  },
  {
    title: 'Activity',
    items: [
      { label: 'Deposits / withdrawals', key: 'deposit_withdrawals' },
      { label: 'Securities sold', key: 'net_trades_sales' },
      { label: 'Securities bought', key: 'net_trades_purchases' },
    ],
  },
]

/**
 * MTD/YTD income, costs and cash activity, straight from the statement's
 * CashReport (BASE_SUMMARY row).
 */
export function CashFlowCard({ portfolio, hidden }: Props) {
  const [period, setPeriod] = useState<Period>('ytd')
  const cr = portfolio.cash_report

  const val = (key: string): number =>
    (cr[`${key}_${period}` as keyof CashReport] as number) ?? 0

  return (
    <div className="rounded-[var(--radius-lg)] border border-border bg-surface p-5 shadow-[var(--shadow)] sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold tracking-tight text-text">
          Income & costs
        </h2>
        <Segmented options={PERIODS} value={period} onChange={setPeriod} size="sm" />
      </div>

      <div className="mt-2 flex flex-col">
        {GROUPS.map((g) => (
          <div key={g.title}>
            <div className="mt-3 text-[10px] font-medium uppercase tracking-wide text-faint">
              {g.title}
            </div>
            {g.items.map((item) => {
              const v = val(item.key)
              const activity = g.title === 'Activity'
              const tone = activity
                ? 'text-muted'
                : v > 0
                  ? 'text-pos'
                  : v < 0
                    ? 'text-neg'
                    : 'text-faint'
              return (
                <div key={item.key} className="flex items-center justify-between py-1.5">
                  <span className="text-[12px] text-text">{item.label}</span>
                  <span className={`tnum text-[12px] font-medium ${tone} ${hidden ? 'masked' : ''}`}>
                    {v === 0
                      ? '—'
                      : `${!activity && v > 0 ? '+' : ''}${fmtUSDFull(v, hidden)}`}
                  </span>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
