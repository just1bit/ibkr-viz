import { useEffect, useMemo, useState } from 'react'
import type * as echarts from 'echarts/core'
import type { Holding, Portfolio, Targets } from '../lib/types'
import { fmtQty, fmtUSD, fmtUSDFull } from '../lib/format'
import { displaySymbol } from '../lib/symbols'
import { getChartTheme, paletteFor } from '../lib/chartTheme'
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
 * Unified holdings view — donut chart on the left, positions + rebalance
 * table on the right. Only ticker-level allocation. Hover links the donut
 * sector to its table row and vice versa.
 *
 * Columns: Holding | Value | Day P/L | Day% | Weight | Target | Drift | Action
 * Qty, price, full name appear in a row-hover tooltip.
 */
export function HoldingsCard({ portfolio, savedTargets, onSave, hidden }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('value')
  const [asc, setAsc] = useState(false)
  const [saving, setSaving] = useState(false)
  const [hoverRow, setHoverRow] = useState<string | null>(null)

  const showAccount = portfolio.account_id === 'ALL'
  const totalValue = portfolio.holdings.reduce((s, h) => s + h.market_value, 0)

  // ── Sorted holdings ──
  const rows = useMemo(() => {
    const sorted = [...portfolio.holdings].filter((h) => h.ticker !== 'CASH')
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
  }, [portfolio, sortKey, asc])

  const cashHolding = portfolio.holdings.find((h) => h.ticker === 'CASH')
  const cashValue = cashHolding ? cashHolding.market_value : 0

  // Current hovered holding (for donut center details)
  const hoveredHolding = useMemo(() => {
    if (!hoverRow) return null
    return portfolio.holdings.find((h) => displaySymbol(h) === hoverRow) ?? null
  }, [hoverRow, portfolio.holdings])

  // ── Donut slices ──
  const slices = useMemo(() => {
    const main = rows.map((h, i) => ({
      name: displaySymbol(h),
      value: h.market_value,
      full_name: h.full_name,
      day_pnl: h.day_pnl,
      color: sliceColor(displaySymbol(h), i),
    }))
    const others = cashValue > 0
      ? [{ name: 'Cash', value: cashValue, color: NEUTRAL_GRAY }]
      : []
    return [...main, ...others]
  }, [rows, cashValue])

  // ── Donut chart ──
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

  // ── Rebalance state ──
  const curPcts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const h of rows) m[displaySymbol(h)] = totalValue > 0 ? (h.market_value / totalValue) * 100 : 0
    return m
  }, [rows, totalValue])

  const defaults = useMemo(() => {
    const d: Record<string, string> = {}
    for (const h of rows) {
      const sym = displaySymbol(h)
      d[sym] = String(savedTargets[sym] != null ? savedTargets[sym] : round1(curPcts[sym] ?? 0))
    }
    return d
  }, [rows, savedTargets, curPcts])

  const [edits, setEdits] = useState<Record<string, string>>(defaults)
  useEffect(() => setEdits(defaults), [defaults])

  const tgtPct = (sym: string) => { const v = parseFloat(edits[sym]); return Number.isFinite(v) ? v : 0 }
  const targetSum = rows.reduce((s, h) => s + tgtPct(displaySymbol(h)), 0)
  const balanced = Math.abs(targetSum - 100) < 0.1
  const dirty = rows.some((h) => {
    const sym = displaySymbol(h)
    return String(tgtPct(sym)) !== String(round1(savedTargets[sym] ?? curPcts[sym] ?? 0))
  })

  const reset = () => {
    const d: Record<string, string> = {}
    for (const h of rows) d[displaySymbol(h)] = String(round1(curPcts[displaySymbol(h)] ?? 0))
    setEdits(d)
  }
  const save = async () => {
    setSaving(true)
    try {
      const payload: Targets = {}
      for (const h of rows) payload[displaySymbol(h)] = tgtPct(displaySymbol(h))
      await onSave(payload)
    } finally { setSaving(false) }
  }

  const onSort = (key: SortKey) => {
    if (key === sortKey) setAsc((v) => !v)
    else { setSortKey(key); setAsc(key === 'symbol') }
  }

  return (
    <div className="overflow-visible rounded-[var(--radius-lg)] border border-border bg-surface shadow-[var(--shadow)]">
      {/* ── Header ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5 sm:px-6">
        <div className="flex items-baseline gap-3">
          <h2 className="text-[15px] font-semibold tracking-tight text-text">Holdings</h2>
          <span className="text-[12px] text-faint tabular-nums">{rows.length} positions · {portfolio.date}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-medium tabular-nums ${balanced ? 'text-faint' : 'text-warn'}`}>
            Targets {targetSum.toFixed(1)}%
          </span>
          <button onClick={reset} className="rounded-[8px] px-2 py-0.5 text-[11px] font-medium text-faint transition-colors hover:text-text">Reset</button>
          <button onClick={save} disabled={saving || !dirty || !balanced} className="rounded-[8px] bg-accent px-2.5 py-0.5 text-[11px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {/* ── Body: donut + table ── */}
      <div className="flex flex-col gap-5 p-4 sm:flex-row sm:p-5 sm:pb-6">
        {/* Donut */}
        <div className="relative min-h-[320px] w-full shrink-0 sm:w-[320px]">
          <div ref={elRef} className="absolute inset-0" />
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-4 text-center">
            {hoveredHolding ? (
              <>
                <span className="text-[14px] font-semibold leading-none text-text">{hoverRow}</span>
                <span className="mt-1 max-w-[220px] truncate text-[10px] leading-none text-faint">
                  {hoveredHolding.full_name}
                </span>
                <span className="mt-1.5 text-[20px] font-bold leading-none tabular-nums text-text">
                  {((hoveredHolding.market_value / (totalValue + cashValue)) * 100).toFixed(2)}%
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
                <span className="text-[14px] uppercase tracking-wide text-faint">Total</span>
                <span className={`mt-1 text-[20px] font-bold tabular-nums text-text ${hidden ? 'masked' : ''}`}>
                  {fmtUSD(totalValue + cashValue, hidden)}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Table */}
        <div className="min-w-0 flex-1 overflow-visible">
          <table className="w-full min-w-[680px] border-collapse text-[12px]">
            <thead>
              <tr className="text-[10px] font-medium uppercase tracking-wide text-faint">
                <Th label="Holding" align="left" active={sortKey === 'symbol'} onClick={() => onSort('symbol')} />
                <Th label="Value" align="right" active={sortKey === 'value'} onClick={() => onSort('value')} />
                <Th label="Day P/L" align="right" active={sortKey === 'day_pnl'} onClick={() => onSort('day_pnl')} />
                <Th label="Day%" align="right" active={sortKey === 'day_pct'} onClick={() => onSort('day_pct')} />
                <Th label="Weight" align="right" />
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
                const driftPp = cur - tgt
                const trade = (totalValue * tgt) / 100 - h.market_value
                const action = Math.abs(trade) < totalValue * 0.0005 ? null
                  : trade < 0 ? { label: 'Sell', amt: -trade, tone: 'text-neg' }
                  : { label: 'Buy', amt: trade, tone: 'text-pos' }
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
                      <input
                        type="number" inputMode="numeric" min={0} step={1}
                        value={edits[sym] ?? ''}
                        onChange={(e) => setEdits((p) => ({ ...p, [sym]: e.target.value }))}
                        onBlur={(e) => {
                          const v = parseFloat(e.target.value)
                          if (Number.isFinite(v)) setEdits((p) => ({ ...p, [sym]: String(Math.round(v)) }))
                        }}
                        className="w-14 rounded-[6px] border border-border bg-surface-2 px-1.5 py-0.5 text-right tabular-nums text-[12px] text-text outline-none focus:border-accent"
                      />
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
      </div>
    </div>
  )
}

// ── Helpers ──

function dayPct(h: Holding): number {
  if (!h.prev_close_price || !h.mark_price) return 0
  return ((h.mark_price - h.prev_close_price) / h.prev_close_price) * 100
}

function tone(v: number) { return v > 0 ? 'text-pos' : v < 0 ? 'text-neg' : 'text-faint' }

function sliceColor(name: string, i: number): string {
  return name === 'CASH' || name === 'Cash' ? NEUTRAL_GRAY : paletteFor(i)
}

function Th({ label, align, active, onClick }: { label: string; align: 'left' | 'right'; active?: boolean; onClick?: () => void }) {
  return (
    <th className={`whitespace-nowrap border-b border-border px-1.5 pb-2 font-medium ${align === 'right' ? 'text-right' : 'text-left'} ${onClick ? 'cursor-pointer select-none hover:text-text' : ''} ${active ? 'text-text' : ''}`} onClick={onClick}>
      {label}{active && <span className="ml-0.5">↕</span>}
    </th>
  )
}

function Td({ align, className = '', children }: { align: 'left' | 'right'; className?: string; children: React.ReactNode }) {
  return <td className={`px-1.5 py-3 tabular-nums text-muted ${align === 'right' ? 'text-right' : ''} ${className}`}>{children}</td>
}

// ── Donut chart option ──

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
      emphasis: { scale: true, scaleSize: 6, itemStyle: { shadowBlur: 14, shadowColor: 'rgba(0,0,0,0.25)' } },
      startAngle: 90,
      data: slices.map((d) => ({ name: d.name, value: d.value, full_name: d.full_name, day_pnl: d.day_pnl, itemStyle: { color: d.color } })),
    }],
    animationDuration: 700,
    animationEasing: 'cubicOut',
  } as echarts.EChartsCoreOption
}
