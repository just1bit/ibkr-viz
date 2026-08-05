import { useEffect, useMemo, useState } from 'react'
import type * as echarts from 'echarts/core'
import type { Holding, Portfolio, Targets } from '../lib/types'
import { fmtQty, fmtUSD, fmtUSDFull } from '../lib/format'
import { displaySymbol } from '../lib/symbols'
import { chartEmphasisItemStyle, getChartTheme, paletteFor } from '../lib/chartTheme'
import { useEChart } from '../hooks/useEChart'

interface Props {
  portfolio: Portfolio
  savedTargets: Targets
  onSave: (t: Targets) => Promise<void>
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

const NEUTRAL_GRAY = '#8b8b94'
const round1 = (n: number) => Math.round(n * 10) / 10

/**
 * Round allocation weights to tenths while preserving an exact 100.0% total.
 * The largest-remainder method avoids making the final row absorb all of the
 * visible rounding error.
 */
function allocationWeights(holdings: Holding[], total: number): Record<string, number> {
  const result: Record<string, number> = {}
  if (total <= 0 || holdings.length === 0) return result

  const parts = holdings.map((h, index) => {
    const exactTenths = (Math.max(h.market_value, 0) / total) * 1000
    const floorTenths = Math.floor(exactTenths)
    return {
      symbol: displaySymbol(h),
      index,
      floorTenths,
      remainder: exactTenths - floorTenths,
    }
  })
  let unitsLeft = 1000 - parts.reduce((sum, p) => sum + p.floorTenths, 0)
  parts.sort((a, b) => b.remainder - a.remainder || a.index - b.index)
  for (const part of parts) {
    if (unitsLeft > 0) {
      part.floorTenths += 1
      unitsLeft -= 1
    }
  }
  for (const part of parts) result[part.symbol] = part.floorTenths / 10
  return result
}

/**
 * Unified holdings view — donut chart on the left, positions + rebalance
 * table on the right. Only ticker-level allocation. Hover links the donut
 * sector to its table row and vice versa.
 *
 * Columns: Holding | Value | Day P/L | Day% | Weight | Target | Drift | Action
 * Hover details appear in the donut center and chart tooltip.
 */
export function HoldingsCard({ portfolio, savedTargets, onSave, hidden }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('value')
  const [asc, setAsc] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState(false)
  const [hoverRow, setHoverRow] = useState<string | null>(null)

  const showAccount = portfolio.account_id === 'ALL'
  const marketValue = portfolio.summary.total_value

  // This card intentionally excludes cash/margin: it is a pure view of
  // securities market value, allocation, targets, and rebalance actions.
  const positions = useMemo(
    () => portfolio.holdings.filter((h) => h.ticker !== 'CASH'),
    [portfolio.holdings],
  )

  const rows = useMemo(() => {
    const sorted = [...positions]
    const dir = asc ? 1 : -1
    sorted.sort((a, b) => {
      switch (sortKey) {
        case 'symbol': return dir * displaySymbol(a).localeCompare(displaySymbol(b))
        case 'day_pnl': return dir * (a.day_pnl - b.day_pnl)
        case 'day_pct': return dir * (dayPct(a) - dayPct(b))
        default: return dir * (a.market_value - b.market_value)
      }
    })
    return sorted
  }, [positions, sortKey, asc])

  const allocationTotal = useMemo(
    () => positions.reduce((sum, h) => sum + Math.max(h.market_value, 0), 0),
    [positions],
  )

  const hoveredHolding = useMemo(() => {
    if (!hoverRow) return null
    return positions.find((h) => displaySymbol(h) === hoverRow) ?? null
  }, [hoverRow, positions])

  const slices = useMemo(() => {
    return rows.map((h, i) => ({
      name: displaySymbol(h),
      value: h.market_value,
      full_name: h.full_name,
      day_pnl: h.day_pnl,
      color: sliceColor(i),
    }))
  }, [rows])

  const { elRef, chartRef } = useEChart(
    () => donutOption(slices, hidden),
    [slices, hidden],
  )

  function highlightSector(name: string | null) {
    setHoverRow(name)
    const chart = chartRef.current
    if (!chart) return
    chart.dispatchAction({ type: 'downplay', seriesIndex: 0 })
    if (name) chart.dispatchAction({ type: 'highlight', seriesIndex: 0, name })
  }

  // Rebalance weights are an allocation of invested securities, not a
  // percent of NAV. Keeping cash/margin outside this denominator makes the
  // target model stable for both cash and leveraged accounts.
  const curPcts = useMemo(
    () => allocationWeights(positions, allocationTotal),
    [positions, allocationTotal],
  )

  const defaults = useMemo(() => {
    const d: Record<string, string> = {}
    for (const h of positions) {
      const sym = displaySymbol(h)
      d[sym] = String(round1(savedTargets[sym] ?? curPcts[sym] ?? 0))
    }
    return d
  }, [positions, savedTargets, curPcts])

  const [edits, setEdits] = useState<Record<string, string>>(defaults)
  useEffect(() => {
    setEdits(defaults)
    setEditing(false)
  }, [defaults])

  const tgtPct = (sym: string) => {
    const value = parseFloat(edits[sym])
    return Number.isFinite(value) ? round1(value) : 0
  }
  const targetSum = positions.reduce((s, h) => s + tgtPct(displaySymbol(h)), 0)
  const validTargets = positions.every((h) => {
    const value = parseFloat(edits[displaySymbol(h)])
    return Number.isFinite(value) && value >= 0
  })
  const balanced = validTargets && Math.abs(targetSum - 100) < 0.0001
  const dirty = positions.some((h) => {
    const sym = displaySymbol(h)
    return String(tgtPct(sym)) !== String(round1(savedTargets[sym] ?? curPcts[sym] ?? 0))
  })

  const targetStatus = !validTargets
    ? 'Targets must be 0% or more'
    : balanced
      ? 'Total 100.0%'
      : targetSum < 100
        ? `${(100 - targetSum).toFixed(1)}% remaining`
        : `${(targetSum - 100).toFixed(1)}% over`

  const startEditing = () => {
    setEdits(defaults)
    setEditing(true)
  }

  const cancelEditing = () => {
    setEdits(defaults)
    setEditing(false)
  }

  const reset = () => {
    const d: Record<string, string> = {}
    for (const h of positions) d[displaySymbol(h)] = String(round1(curPcts[displaySymbol(h)] ?? 0))
    setEdits(d)
  }
  const save = async () => {
    setSaving(true)
    try {
      const payload: Targets = {}
      for (const h of positions) payload[displaySymbol(h)] = tgtPct(displaySymbol(h))
      await onSave(payload)
      setEditing(false)
    } finally { setSaving(false) }
  }

  const onSort = (key: SortKey) => {
    if (key === sortKey) setAsc((v) => !v)
    else { setSortKey(key); setAsc(key === 'symbol') }
  }

  return (
    <div className="overflow-visible rounded-[var(--radius-lg)] border border-border bg-surface shadow-[var(--shadow)]">
      <div className="grid grid-cols-1 gap-2 px-5 pt-5 sm:h-[46px] sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:gap-3 sm:px-6">
        <div className="flex items-baseline gap-3">
          <h2 className="text-[15px] font-semibold tracking-tight text-text">Holdings</h2>
          <span className="text-[12px] text-faint tabular-nums">{rows.length} positions · {portfolio.date}</span>
        </div>
        <div className="flex h-11 min-w-0 items-center justify-end gap-2 sm:h-[26px]">
          {editing ? (
            <>
              <span className={`text-[11px] font-medium tabular-nums ${balanced ? 'text-pos' : 'text-warn'}`}>
                {targetStatus}
              </span>
              <button onClick={reset} disabled={saving} className="h-11 rounded-[8px] px-3 text-[11px] font-medium text-faint transition-colors hover:text-text disabled:opacity-40 sm:h-auto sm:px-2 sm:py-0.5">Reset</button>
              <button onClick={cancelEditing} disabled={saving} className="h-11 rounded-[8px] border border-border px-3 text-[11px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-text disabled:opacity-40 sm:h-auto sm:py-0.5">Cancel</button>
              <button onClick={save} disabled={saving || !dirty || !balanced} className="h-11 rounded-[8px] bg-accent px-3 text-[11px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40 sm:h-auto sm:px-2.5 sm:py-0.5">
                {saving ? 'Saving…' : 'Save'}
              </button>
            </>
          ) : (
            <>
              <span className="text-[11px] font-medium tabular-nums text-faint">Targets {targetSum.toFixed(1)}%</span>
              <button onClick={startEditing} className="flex h-11 items-center gap-1.5 rounded-[8px] border border-border bg-surface px-3 text-[11px] font-medium text-text transition-colors hover:bg-surface-2 sm:h-auto sm:py-1">
                <EditIcon />
                Edit
              </button>
            </>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-5 p-4 sm:flex-row sm:p-5 sm:pb-6">
        <div className="relative h-[320px] w-full shrink-0 self-start sm:w-[320px]">
          <div ref={elRef} className="absolute inset-0" />
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-4 text-center">
            {hoveredHolding ? (
              <>
                <span className="text-[14px] font-semibold leading-none text-text">{hoverRow}</span>
                <span className="mt-1 max-w-[220px] truncate text-[10px] leading-none text-faint">
                  {hoveredHolding.full_name}
                </span>
                <span className="mt-1.5 text-[20px] font-bold leading-none tabular-nums text-text">
                  {((hoveredHolding.market_value / (allocationTotal || 1)) * 100).toFixed(2)}%
                </span>
                <span className={`mt-2 text-[12px] leading-none text-faint ${hidden ? 'masked' : ''}`}>
                  {fmtUSDFull(hoveredHolding.market_value, hidden)}
                </span>
                <span className="mt-1 text-[11px] leading-none text-faint">
                  {hoveredHolding.ticker !== 'CASH' && <span>Qty {fmtQty(hoveredHolding.quantity)} · </span>}
                  {hoveredHolding.mark_price != null && <span>Price {fmtUSDFull(hoveredHolding.mark_price, hidden)}</span>}
                </span>
              </>
            ) : (
              <>
                <span className="text-[12px] uppercase tracking-wide text-faint">Market Value</span>
                <span className={`mt-1 text-[20px] font-bold tabular-nums text-text ${hidden ? 'masked' : ''}`}>
                  {fmtUSD(marketValue, hidden)}
                </span>
                <span className="mt-2 text-[11px] leading-none text-faint">{rows.length} positions</span>
              </>
            )}
          </div>
        </div>

        <div className="hidden min-w-0 flex-1 overflow-x-auto scroll-thin sm:block">
          <table className="w-full min-w-[780px] table-fixed border-collapse text-[12px]">
            <colgroup>
              <col className="w-[23.25%]" />
              <col className="w-[15.75%]" />
              <col className="w-[10.9%]" />
              <col className="w-[8.9%]" />
              <col className="w-[13.7%]" />
              <col className="w-[8.5%]" />
              <col className="w-[6.75%]" />
              <col className="w-[12.25%]" />
            </colgroup>
            <thead>
              <tr className="text-[10px] font-medium uppercase tracking-wide text-faint">
                <Th label="Holding" align="left" active={sortKey === 'symbol'} onClick={() => onSort('symbol')} />
                <Th label="Market Value" align="right" active={sortKey === 'value'} onClick={() => onSort('value')} />
                <Th label="Day P/L" align="right" active={sortKey === 'day_pnl'} onClick={() => onSort('day_pnl')} />
                <Th label="Day%" align="right" active={sortKey === 'day_pct'} onClick={() => onSort('day_pct')} />
                <Th label="Allocation" align="right" />
                <Th label="Target" align="right" />
                <Th label="Drift" align="right" />
                <Th label="Action" align="right" />
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => {
                const sym = displaySymbol(h)
                const cur = curPcts[sym] ?? 0
                const tgt = tgtPct(sym)
                const { driftPp, action } = rebalanceMetrics(cur, tgt, allocationTotal)
                const active = hoverRow === sym

                return (
                  <tr
                    key={`${h.account_id}-${h.ticker}`}
                    onMouseEnter={() => highlightSector(sym)}
                    onMouseLeave={() => highlightSector(null)}
                    className={`group border-b border-border/60 last:border-0 transition-colors ${active ? 'bg-surface-2/80' : 'hover:bg-surface-2/40'}`}
                  >
                    <Td align="left" className="relative">
                      <div className="flex items-center gap-1.5">
                        <span
                          className="h-2 w-2 shrink-0 rounded-[2px]"
                          style={{ background: slices.find((s) => s.name === sym)?.color ?? NEUTRAL_GRAY }}
                        />
                        <span className="font-semibold text-text">{sym}</span>
                        <span className={`rounded-full px-1.5 py-px text-[9px] font-semibold tracking-wide ${CLASS_TONE[h.asset_class] ?? 'bg-faint/10 text-muted'}`}>
                          {h.asset_class}
                        </span>
                        {showAccount && (
                          <span className="rounded-full border border-border px-1.5 py-px text-[9px] font-medium text-faint">
                            {portfolio.aliases[h.account_id] || h.account_id}
                          </span>
                        )}
                      </div>
                    </Td>
                    <Td align="right" className={`font-semibold text-text ${hidden ? 'masked' : ''}`}>
                      {fmtUSDFull(h.market_value, hidden)}
                    </Td>
                    <Td align="right" className={`font-medium ${tone(h.day_pnl)} ${hidden ? 'masked' : ''}`}>
                      {h.day_pnl >= 0 ? '+' : ''}{fmtUSDFull(h.day_pnl, hidden)}
                    </Td>
                    <Td align="right" className={h.ticker === 'CASH' ? 'text-faint' : tone(dayPct(h))}>
                      {!h.prev_close_price ? '—' : `${dayPct(h) >= 0 ? '+' : ''}${dayPct(h).toFixed(2)}%`}
                    </Td>
                    <Td align="right">
                      <div className="flex items-center justify-end gap-1">
                        <div className="h-1 w-8 overflow-hidden rounded-full bg-surface-2">
                          <div className="h-full rounded-full bg-accent/70" style={{ width: `${Math.min(cur, 100)}%` }} />
                        </div>
                        <span className="w-10 tabular-nums text-muted">{cur.toFixed(1)}%</span>
                      </div>
                    </Td>
                    <Td align="right">
                      {editing ? (
                        <TargetInput
                          symbol={sym}
                          value={edits[sym] ?? ''}
                          onChange={(value) => setEdits((p) => ({ ...p, [sym]: value }))}
                          compact
                        />
                      ) : (
                        <span className="font-medium text-text">{tgt.toFixed(1)}%</span>
                      )}
                    </Td>
                    <Td align="right" className={Math.abs(driftPp) < 0.05 ? 'text-faint' : 'text-muted'}>
                      {driftPp >= 0 ? '+' : ''}{driftPp.toFixed(1)}
                    </Td>
                    <Td align="right" className={`font-medium ${action ? action.tone : 'text-faint'}`}>
                      {action ? `${action.label} ${fmtUSD(action.amt, hidden)}` : '—'}
                    </Td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Mobile holdings list: keeps allocation and rebalance controls in
            view instead of hiding them beyond a 680px horizontal table. */}
        <div className="min-w-0 flex-1 space-y-2 sm:hidden">
          {rows.map((h) => {
            const sym = displaySymbol(h)
            const cur = curPcts[sym] ?? 0
            const tgt = tgtPct(sym)
            const { driftPp, action } = rebalanceMetrics(cur, tgt, allocationTotal)

            return (
              <div key={`${h.account_id}-${h.ticker}-mobile`} className="rounded-[12px] border border-border/70 bg-surface-2/35 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: slices.find((s) => s.name === sym)?.color ?? NEUTRAL_GRAY }} />
                      <span className="font-semibold text-text">{sym}</span>
                      <span className={`rounded-full px-1.5 py-px text-[9px] font-semibold tracking-wide ${CLASS_TONE[h.asset_class] ?? 'bg-faint/10 text-muted'}`}>{h.asset_class}</span>
                    </div>
                    <div className="mt-1 truncate text-[10px] text-faint">{h.full_name}</div>
                  </div>
                  <div className={`shrink-0 text-right text-[13px] font-semibold tabular-nums text-text ${hidden ? 'masked' : ''}`}>
                    {fmtUSDFull(h.market_value, hidden)}
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border/60 pt-3">
                  <MobileMetric label="Day P/L">
                    <span className={`font-medium ${tone(h.day_pnl)} ${hidden ? 'masked' : ''}`}>
                      {h.day_pnl >= 0 ? '+' : ''}{fmtUSDFull(h.day_pnl, hidden)}
                      <span className="ml-1 text-[10px]">{h.prev_close_price ? `(${dayPct(h) >= 0 ? '+' : ''}${dayPct(h).toFixed(2)}%)` : ''}</span>
                    </span>
                  </MobileMetric>
                  <MobileMetric label="Allocation / drift">
                    <span className="text-text">{cur.toFixed(1)}%</span>
                    <span className={`ml-1 text-[10px] ${Math.abs(driftPp) < 0.05 ? 'text-faint' : 'text-muted'}`}>
                      ({driftPp >= 0 ? '+' : ''}{driftPp.toFixed(1)}pp)
                    </span>
                  </MobileMetric>
                  <MobileMetric label="Target">
                    {editing ? (
                      <TargetInput
                        symbol={sym}
                        value={edits[sym] ?? ''}
                        onChange={(value) => setEdits((p) => ({ ...p, [sym]: value }))}
                      />
                    ) : (
                      <span className="font-medium text-text">{tgt.toFixed(1)}%</span>
                    )}
                  </MobileMetric>
                  <MobileMetric label="Action">
                    <span className={`font-medium ${action ? action.tone : 'text-faint'}`}>
                      {action ? `${action.label} ${fmtUSD(action.amt, hidden)}` : '—'}
                    </span>
                  </MobileMetric>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function dayPct(h: Holding): number {
  if (!h.prev_close_price || !h.mark_price) return 0
  return ((h.mark_price - h.prev_close_price) / h.prev_close_price) * 100
}

function tone(v: number) { return v > 0 ? 'text-pos' : v < 0 ? 'text-neg' : 'text-faint' }

/**
 * Keep Drift and Action on the same one-decimal allocation model shown in the
 * table. A zero displayed drift must therefore always produce no action.
 */
function rebalanceMetrics(current: number, target: number, allocationValue: number) {
  const driftPp = round1(current - target)
  if (Math.abs(driftPp) < 0.05) return { driftPp, action: null }

  const trade = (allocationValue * -driftPp) / 100
  return {
    driftPp,
    action: trade < 0
      ? { label: 'Sell', amt: -trade, tone: 'text-neg' }
      : { label: 'Buy', amt: trade, tone: 'text-pos' },
  }
}

function sliceColor(i: number): string {
  return paletteFor(i)
}

function Th({ label, align, active, onClick }: { label: string; align: 'left' | 'right'; active?: boolean; onClick?: () => void }) {
  return (
    <th className={`whitespace-nowrap border-b border-border px-1.5 pb-2 font-medium ${align === 'right' ? 'text-right' : 'text-left'} ${onClick ? 'cursor-pointer select-none hover:text-text' : ''} ${active ? 'text-text' : ''}`} onClick={onClick}>
      {label}{active && <span className="ml-0.5">↕</span>}
    </th>
  )
}

function Td({ align, className = '', children }: { align: 'left' | 'right'; className?: string; children: React.ReactNode }) {
  return <td className={`h-[43px] px-1.5 py-0 tabular-nums text-muted ${align === 'right' ? 'text-right' : ''} ${className}`}>{children}</td>
}

function MobileMetric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-[9px] font-medium uppercase tracking-wide text-faint">{label}</div>
      <div className="h-11 text-[12px] tabular-nums text-muted">{children}</div>
    </div>
  )
}

function TargetInput({
  symbol,
  value,
  onChange,
  compact = false,
}: {
  symbol: string
  value: string
  onChange: (value: string) => void
  compact?: boolean
}) {
  return (
    <label className="inline-flex items-center gap-1">
      <input
        aria-label={`${symbol} target allocation`}
        type="number"
        inputMode="decimal"
        min={0}
        step={0.1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={(e) => {
          const parsed = parseFloat(e.target.value)
          if (Number.isFinite(parsed)) onChange(String(round1(parsed)))
        }}
        className={compact
          ? 'w-14 rounded-[6px] border border-accent/50 bg-accent/5 px-1.5 py-0.5 text-right text-[12px] tabular-nums text-text outline-none focus:border-accent focus:ring-2 focus:ring-accent/15'
          : 'h-11 w-20 rounded-[8px] border border-accent/50 bg-surface px-2 text-right text-[16px] tabular-nums text-text outline-none focus:border-accent focus:ring-2 focus:ring-accent/15'}
      />
      <span className="text-muted">%</span>
    </label>
  )
}

function EditIcon() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M10.8 2.2a1.4 1.4 0 0 1 2 2L5.1 11.9l-2.6.6.6-2.6 7.7-7.7Z" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function donutOption(slices: { name: string; value: number; full_name?: string; day_pnl?: number; color: string }[], hidden: boolean): echarts.EChartsCoreOption {
  const t = getChartTheme()
  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: t.text, fontSize: 12 },
      extraCssText: 'border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,0.18);',
      formatter: (p: { name: string; value: number; percent: number; data: { full_name?: string; day_pnl?: number } }) => {
        const usd = hidden ? '••••' : '$' + p.value.toLocaleString()
        const fn = p.data?.full_name ? `<div style="color:${t.faint};font-size:10px;margin-top:2px">${p.data.full_name}</div>` : ''
        const dp = p.data?.day_pnl
        const day = dp != null && dp !== 0
          ? `<div style="margin-top:2px;font-variant-numeric:tabular-nums;color:${dp >= 0 ? '#22a06b' : '#e5484d'}">${dp >= 0 ? '+' : ''}${hidden ? '••••' : '$' + dp.toLocaleString()} today</div>`
          : ''
        return `<div style="font-weight:600">${p.name}</div>${fn}<div style="margin-top:4px;font-variant-numeric:tabular-nums">${usd} · ${p.percent.toFixed(2)}%</div>${day}`
      },
    },
    series: [{
      type: 'pie',
      radius: ['62%', '88%'],
      center: ['50%', '50%'],
      padAngle: 2,
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 5, borderColor: t.surface, borderWidth: 3 },
      label: { show: false },
      labelLine: { show: false },
      emphasis: { scale: true, scaleSize: 6, itemStyle: chartEmphasisItemStyle },
      startAngle: 90,
      data: slices.map((d) => ({ name: d.name, value: d.value, full_name: d.full_name, day_pnl: d.day_pnl, itemStyle: { color: d.color } })),
    }],
    animationDuration: 700,
    animationEasing: 'cubicOut',
  } as echarts.EChartsCoreOption
}
