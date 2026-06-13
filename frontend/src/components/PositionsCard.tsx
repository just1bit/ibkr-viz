import { useMemo, useState } from 'react'
import type { Holding, Portfolio } from '../lib/types'
import { fmtQty, fmtUSDFull } from '../lib/format'
import { displaySymbol, optionTerms } from '../lib/symbols'

interface Props {
  portfolio: Portfolio
  hidden: boolean
}

type SortKey = 'value' | 'day_pnl' | 'day_pct' | 'symbol'

const CLASS_TONE: Record<string, string> = {
  ETF: 'bg-accent/10 text-accent',
  STOCK: 'bg-[#60a5fa]/12 text-[#3b82f6] dark:text-[#60a5fa]',
  OPTION: 'bg-[#a78bfa]/12 text-[#7c3aed] dark:text-[#a78bfa]',
  BOND: 'bg-[#f0a868]/15 text-[#d97706] dark:text-[#f0a868]',
  CASH: 'bg-faint/10 text-muted',
}

/**
 * Full positions table: every statement figure per holding — quantity, mark
 * price, day move (prev close → close), day P&L, market value, weight.
 * Options get their contract terms; cost columns light up automatically once
 * the Flex query starts delivering cost basis.
 */
export function PositionsCard({ portfolio, hidden }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('value')
  const [asc, setAsc] = useState(false)

  const showAccount = portfolio.account_id === 'ALL'
  const hasCost = portfolio.holdings.some((h) => (h.cost_basis ?? 0) !== 0)
  const totalValue = portfolio.holdings.reduce((s, h) => s + h.market_value, 0)

  const rows = useMemo(() => {
    const sorted = [...portfolio.holdings]
    const dir = asc ? 1 : -1
    sorted.sort((a, b) => {
      switch (sortKey) {
        case 'symbol':
          return dir * displaySymbol(a).localeCompare(displaySymbol(b))
        case 'day_pnl':
          return dir * (a.day_pnl - b.day_pnl)
        case 'day_pct':
          return dir * (dayPct(a) - dayPct(b))
        default:
          return dir * (a.market_value - b.market_value)
      }
    })
    return sorted
  }, [portfolio, sortKey, asc])

  const onSort = (key: SortKey) => {
    if (key === sortKey) setAsc((v) => !v)
    else {
      setSortKey(key)
      setAsc(key === 'symbol')
    }
  }

  return (
    <div className="rounded-[var(--radius-lg)] border border-border bg-surface shadow-[var(--shadow)]">
      <div className="flex items-baseline justify-between gap-3 px-5 pt-5 sm:px-6">
        <h2 className="text-[15px] font-semibold tracking-tight text-text">
          Positions
        </h2>
        <span className="text-[12px] text-faint tnum">
          {portfolio.holdings.length} holdings · {portfolio.date}
        </span>
      </div>

      <div className="scroll-thin mt-3 overflow-x-auto pb-2">
        <table className="w-full min-w-[640px] border-collapse text-[12.5px]">
          <thead>
            <tr className="text-[10px] font-medium uppercase tracking-wide text-faint">
              <Th
                label="Holding"
                align="left"
                active={sortKey === 'symbol'}
                onClick={() => onSort('symbol')}
                className="pl-5 sm:pl-6"
              />
              <Th label="Qty" align="right" />
              <Th label="Price" align="right" />
              <Th
                label="Day %"
                align="right"
                active={sortKey === 'day_pct'}
                onClick={() => onSort('day_pct')}
              />
              <Th
                label="Day P/L"
                align="right"
                active={sortKey === 'day_pnl'}
                onClick={() => onSort('day_pnl')}
              />
              {hasCost && <Th label="Unrealized" align="right" />}
              <Th
                label="Value"
                align="right"
                active={sortKey === 'value'}
                onClick={() => onSort('value')}
              />
              <Th label="Weight" align="right" className="pr-5 sm:pr-6" />
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <PositionRow
                key={`${h.account_id}-${h.ticker}`}
                h={h}
                hidden={hidden}
                showAccount={showAccount}
                hasCost={hasCost}
                weight={totalValue > 0 ? (h.market_value / totalValue) * 100 : 0}
                alias={portfolio.aliases[h.account_id] || h.account_id}
                reportDate={portfolio.date}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function dayPct(h: Holding): number {
  if (!h.prev_close_price || !h.mark_price) return 0
  return ((h.mark_price - h.prev_close_price) / h.prev_close_price) * 100
}

function Th({
  label,
  align,
  active,
  onClick,
  className = '',
}: {
  label: string
  align: 'left' | 'right'
  active?: boolean
  onClick?: () => void
  className?: string
}) {
  return (
    <th
      className={`whitespace-nowrap border-b border-border px-3 pb-2 font-medium ${
        align === 'right' ? 'text-right' : 'text-left'
      } ${onClick ? 'cursor-pointer select-none hover:text-text' : ''} ${
        active ? 'text-text' : ''
      } ${className}`}
      onClick={onClick}
    >
      {label}
      {active && <span className="ml-0.5">↕</span>}
    </th>
  )
}

function PositionRow({
  h,
  hidden,
  showAccount,
  hasCost,
  weight,
  alias,
  reportDate,
}: {
  h: Holding
  hidden: boolean
  showAccount: boolean
  hasCost: boolean
  weight: number
  alias: string
  reportDate: string
}) {
  const isCash = h.ticker === 'CASH'
  const pct = dayPct(h)
  const traded =
    h.prev_close_quantity != null &&
    h.prev_close_quantity !== 0 &&
    h.prev_close_quantity !== h.quantity
  const terms = optionTerms(h, reportDate)
  const tone = (v: number) => (v > 0 ? 'text-pos' : v < 0 ? 'text-neg' : 'text-faint')

  return (
    <tr className="group border-b border-border/60 last:border-0 hover:bg-surface-2/60">
      <td className="py-2.5 pl-5 pr-3 sm:pl-6">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-text">{displaySymbol(h)}</span>
          <span
            className={`rounded-full px-1.5 py-px text-[9px] font-semibold tracking-wide ${
              CLASS_TONE[h.asset_class] ?? 'bg-faint/10 text-muted'
            }`}
          >
            {h.asset_class}
          </span>
          {showAccount && !isCash && (
            <span className="rounded-full border border-border px-1.5 py-px text-[9px] font-medium text-faint">
              {alias}
            </span>
          )}
          {traded && (
            <span
              title={`Quantity changed today: ${fmtQty(h.prev_close_quantity ?? 0)} → ${fmtQty(h.quantity)}`}
              className="h-1.5 w-1.5 rounded-full bg-warn"
            />
          )}
        </div>
        <div className="mt-0.5 max-w-[260px] truncate text-[11px] text-faint">
          {terms ?? h.full_name}
        </div>
      </td>
      <td className="px-3 py-2.5 text-right tnum text-muted">
        {isCash ? '—' : fmtQty(h.quantity)}
      </td>
      <td className="px-3 py-2.5 text-right tnum text-muted">
        {h.mark_price == null ? '—' : fmtUSDFull(h.mark_price, hidden)}
      </td>
      <td className={`px-3 py-2.5 text-right tnum ${isCash ? 'text-faint' : tone(pct)}`}>
        {isCash || !h.prev_close_price
          ? '—'
          : `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`}
      </td>
      <td
        className={`px-3 py-2.5 text-right tnum font-medium ${
          isCash ? 'text-faint' : tone(h.day_pnl)
        } ${hidden ? 'masked' : ''}`}
      >
        {isCash
          ? '—'
          : `${h.day_pnl >= 0 ? '+' : ''}${fmtUSDFull(h.day_pnl, hidden)}`}
      </td>
      {hasCost && (
        <td
          className={`px-3 py-2.5 text-right tnum ${tone(h.unrealized_pnl)} ${hidden ? 'masked' : ''}`}
        >
          {(h.cost_basis ?? 0) === 0
            ? '—'
            : `${h.unrealized_pnl >= 0 ? '+' : ''}${fmtUSDFull(h.unrealized_pnl, hidden)}`}
        </td>
      )}
      <td
        className={`px-3 py-2.5 text-right tnum font-semibold text-text ${hidden ? 'masked' : ''}`}
      >
        {fmtUSDFull(h.market_value, hidden)}
      </td>
      <td className="py-2.5 pl-3 pr-5 text-right sm:pr-6">
        <div className="flex items-center justify-end gap-2">
          <div className="h-1 w-12 overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full rounded-full bg-accent/70"
              style={{ width: `${Math.min(weight, 100)}%` }}
            />
          </div>
          <span className="w-11 tnum text-[11px] text-muted">
            {weight.toFixed(1)}%
          </span>
        </div>
      </td>
    </tr>
  )
}
