import { useEffect, useMemo, useState } from 'react'
import type * as echarts from 'echarts/core'
import type { ExposureSummary, Holding, Portfolio, Targets } from '../lib/types'
import { fmtQty, fmtUSD, fmtUSDFull } from '../lib/format'
import { displaySymbol } from '../lib/symbols'
import { chartEmphasisItemStyle, getChartTheme, paletteFor } from '../lib/chartTheme'
import { useEChart } from '../hooks/useEChart'
import { CardDate, CardTitle, PositionCount } from './CardMeta'

interface Props {
  portfolio: Portfolio
  savedTargets: Targets
  onSave: (t: Targets) => Promise<void>
  hidden: boolean
}

type ExposureMode = 'long' | 'short' | 'gross' | 'net'
type DirectionalMode = Extract<ExposureMode, 'long' | 'short'>
type SortKey = 'value' | 'day_pnl' | 'day_pct' | 'symbol'

const CLASS_TONE: Record<string, string> = {
  ETF: 'bg-accent/10 text-accent',
  STOCK: 'bg-[#60a5fa]/12 text-[#3b82f6] dark:text-[#60a5fa]',
  OPTION: 'bg-[#a78bfa]/12 text-[#7c3aed] dark:text-[#a78bfa]',
  BOND: 'bg-[#f0a868]/15 text-[#d97706] dark:text-[#f0a868]',
  CASH: 'bg-faint/10 text-muted',
}

const MODE_LABEL: Record<ExposureMode, string> = {
  long: 'Long', short: 'Short', gross: 'Gross', net: 'Net',
}

const NEUTRAL_GRAY = '#8b8b94'
const round1 = (n: number) => Math.round(n * 10) / 10

export function HoldingsCard({ portfolio, savedTargets, onSave, hidden }: Props) {
  const [mode, setMode] = useState<ExposureMode>('long')
  const longPositions = useMemo(() => aggregateDirectionalPositions(
    portfolio.holdings.filter((h) => h.market_value > 0),
    portfolio.account_id === 'ALL',
  ), [portfolio.holdings, portfolio.account_id])
  const shortPositions = useMemo(() => aggregateDirectionalPositions(
    portfolio.holdings.filter((h) => h.market_value < 0),
    portfolio.account_id === 'ALL',
  ), [portfolio.holdings, portfolio.account_id])
  const exposures = useMemo(
    () => portfolio.exposures ?? deriveExposureSummary(portfolio.holdings, portfolio.summary.net_liquidation),
    [portfolio],
  )
  const count = mode === 'long'
    ? longPositions.length
    : mode === 'short'
      ? shortPositions.length
      : exposureByInstrument(portfolio.holdings).length

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface shadow-[var(--shadow)]">
      <div className="border-b border-border/70 px-4 py-2 sm:px-6 sm:py-2">
        <div className="flex flex-col gap-2.5 lg:flex-row lg:items-center">
          <div className="flex shrink-0 items-baseline gap-3">
            <CardTitle>Exposure</CardTitle>
            <CardDate date={portfolio.date} />
          </div>

          <div className="flex min-w-0 items-center gap-5 lg:ml-auto">
            <PositionCount count={count} />
            <div className="my-1.5 grid min-w-0 flex-1 grid-flow-col grid-cols-none auto-cols-[84px] overflow-x-auto rounded-[9px] border border-border bg-surface-2/70 px-1 py-1 scroll-thin sm:grid-flow-row sm:grid-cols-4 sm:auto-cols-auto sm:overflow-visible lg:w-[350px] lg:flex-none" role="tablist" aria-label="Exposure type">
              {(['long', 'short', 'gross', 'net'] as ExposureMode[]).map((item) => (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={mode === item}
                  onClick={() => setMode(item)}
                  className={`flex min-w-0 flex-col items-start justify-center rounded-[6px] px-2.5 py-0 text-left transition-colors ${
                    mode === item
                      ? 'bg-surface shadow-sm'
                      : 'hover:bg-surface/60'
                  }`}
                >
                  <span className={`text-[11px] font-semibold uppercase leading-tight tracking-wide sm:text-[12px] ${mode === item ? 'text-text' : 'text-muted'}`}>{MODE_LABEL[item]}</span>
                  <span className={`mt-px text-[10px] font-medium leading-tight tabular-nums sm:text-[11px] ${mode === item ? 'text-muted' : 'text-faint'} ${hidden ? 'masked' : ''}`}>
                    {fmtUSD(exposureTabValue(item, exposures), hidden)}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {mode === 'long' || mode === 'short' ? (
        <DirectionalExposureView
          key={mode}
          mode={mode}
          positions={mode === 'long' ? longPositions : shortPositions}
          savedTargets={savedTargets}
          onSave={onSave}
          hidden={hidden}
        />
      ) : (
        <ExposureOverview mode={mode} portfolio={portfolio} exposures={exposures} hidden={hidden} />
      )}
    </section>
  )
}

function DirectionalExposureView({
  mode,
  positions,
  savedTargets,
  onSave,
  hidden,
}: {
  mode: DirectionalMode
  positions: Holding[]
  savedTargets: Targets
  onSave: (t: Targets) => Promise<void>
  hidden: boolean
}) {
  const [sortKey, setSortKey] = useState<SortKey>('value')
  const [asc, setAsc] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState(false)
  const [hoverRow, setHoverRow] = useState<string | null>(null)

  const rows = useMemo(() => {
    const sorted = [...positions]
    const dir = asc ? 1 : -1
    sorted.sort((a, b) => {
      switch (sortKey) {
        case 'symbol': return dir * displaySymbol(a).localeCompare(displaySymbol(b))
        case 'day_pnl': return dir * (a.day_pnl - b.day_pnl)
        case 'day_pct': return dir * (positionDayPct(a) - positionDayPct(b))
        default: return dir * (exposureValue(a) - exposureValue(b))
      }
    })
    return sorted
  }, [positions, sortKey, asc])

  const allocationTotal = useMemo(
    () => positions.reduce((sum, h) => sum + exposureValue(h), 0),
    [positions],
  )
  const curPcts = useMemo(
    () => allocationWeights(positions, allocationTotal),
    [positions, allocationTotal],
  )
  const hoveredHolding = useMemo(() => {
    if (!hoverRow) return null
    return positions.find((h) => displaySymbol(h) === hoverRow) ?? null
  }, [hoverRow, positions])
  const slices = useMemo(
    () => rows.map((h, i) => ({
      name: displaySymbol(h),
      value: exposureValue(h),
      full_name: h.full_name,
      day_pnl: h.day_pnl,
      color: paletteFor(i),
    })),
    [rows],
  )
  const { elRef, chartRef } = useEChart(
    () => donutOption(slices, hidden),
    [slices, hidden],
  )

  const sideHasSavedTargets = useMemo(() => positions.some((h) => (
    savedTargets[targetStorageKey(mode, displaySymbol(h))] != null
  )), [mode, positions, savedTargets])
  const defaults = useMemo(() => {
    const d: Record<string, string> = {}
    for (const h of positions) {
      const sym = displaySymbol(h)
      const saved = savedTargets[targetStorageKey(mode, sym)]
      d[sym] = String(round1(saved ?? (sideHasSavedTargets ? 0 : curPcts[sym] ?? 0)))
    }
    return d
  }, [mode, positions, savedTargets, sideHasSavedTargets, curPcts])
  const [edits, setEdits] = useState<Record<string, string>>(defaults)

  useEffect(() => {
    setEdits(defaults)
    setEditing(false)
  }, [defaults])

  const tgtPct = (sym: string) => {
    const value = parseFloat(edits[sym])
    return Number.isFinite(value) ? round1(value) : 0
  }
  const targetSum = positions.reduce((sum, h) => sum + tgtPct(displaySymbol(h)), 0)
  const validTargets = positions.every((h) => {
    const value = parseFloat(edits[displaySymbol(h)])
    return Number.isFinite(value) && value >= 0
  })
  const balanced = positions.length > 0 && validTargets && Math.abs(targetSum - 100) < 0.0001
  const dirty = positions.some((h) => {
    const sym = displaySymbol(h)
    return String(tgtPct(sym)) !== defaults[sym]
  })
  const targetStatus = !validTargets
    ? 'Targets must be 0% or more'
    : balanced
      ? 'Total 100.0%'
      : targetSum < 100
        ? `${(100 - targetSum).toFixed(1)}% remaining`
        : `${(targetSum - 100).toFixed(1)}% over`

  const save = async () => {
    setSaving(true)
    try {
      const payload = { ...savedTargets }
      for (const h of positions) {
        const sym = displaySymbol(h)
        payload[targetStorageKey(mode, sym)] = tgtPct(sym)
      }
      await onSave(payload)
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }
  const reset = () => {
    const d: Record<string, string> = {}
    for (const h of positions) d[displaySymbol(h)] = String(round1(curPcts[displaySymbol(h)] ?? 0))
    setEdits(d)
  }
  const onSort = (key: SortKey) => {
    if (key === sortKey) setAsc((value) => !value)
    else {
      setSortKey(key)
      setAsc(key === 'symbol')
    }
  }
  const highlightSector = (name: string | null) => {
    setHoverRow(name)
    const chart = chartRef.current
    if (!chart) return
    chart.dispatchAction({ type: 'downplay', seriesIndex: 0 })
    if (name) chart.dispatchAction({ type: 'highlight', seriesIndex: 0, name })
  }

  if (positions.length === 0) {
    return (
      <div className="flex min-h-[280px] flex-col items-center justify-center px-6 py-14 text-center">
        <div className={`flex h-11 w-11 items-center justify-center rounded-full ${mode === 'long' ? 'bg-accent/10 text-accent' : 'bg-neg/10 text-neg'}`}>
          <ExposureIcon mode={mode} />
        </div>
        <p className="mt-3 text-[14px] font-semibold text-text">No {mode} exposure</p>
        <p className="mt-1 max-w-sm text-[12px] leading-relaxed text-muted">
          {mode === 'short'
            ? 'There are no short securities or negative cash balances in this account.'
            : 'There are no long securities or positive cash balances in this account.'}
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex min-h-[48px] flex-wrap items-center justify-between gap-2 border-b border-border/60 px-4 py-2 sm:px-6">
        <div className="flex items-center gap-2 text-[11px] text-faint">
          <span className={`h-2 w-2 rounded-full ${mode === 'long' ? 'bg-accent' : 'bg-neg'}`} />
          <span>{mode === 'long' ? 'Long allocation' : 'Short-book allocation'}</span>
        </div>
        <div className="flex items-center justify-end gap-2">
          {editing ? (
            <>
              <span className={`text-[11px] font-medium tabular-nums ${balanced ? 'text-pos' : 'text-warn'}`}>{targetStatus}</span>
              <button onClick={reset} disabled={saving} className="rounded-[8px] px-2 py-1 text-[11px] font-medium text-faint hover:text-text disabled:opacity-40">Reset</button>
              <button onClick={() => { setEdits(defaults); setEditing(false) }} disabled={saving} className="rounded-[8px] border border-border px-2.5 py-1 text-[11px] font-medium text-muted hover:bg-surface-2 disabled:opacity-40">Cancel</button>
              <button onClick={save} disabled={saving || !dirty || !balanced} className="rounded-[8px] bg-accent px-2.5 py-1 text-[11px] font-medium text-white hover:opacity-90 disabled:opacity-40">
                {saving ? 'Saving…' : 'Save'}
              </button>
            </>
          ) : (
            <>
              <span className="text-[11px] font-medium tabular-nums text-faint">Targets {targetSum.toFixed(1)}%</span>
              <button onClick={() => { setEdits(defaults); setEditing(true) }} className="flex items-center gap-1.5 rounded-[8px] border border-border bg-surface px-2.5 py-1 text-[11px] font-medium text-text hover:bg-surface-2">
                <EditIcon /> Edit
              </button>
            </>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-3 p-4 sm:gap-5 sm:p-5 sm:pb-6 xl:flex-row">
        <div className="relative h-[248px] w-full shrink-0 self-start sm:h-[280px] xl:h-[320px] xl:w-[320px]">
          <div ref={elRef} className="absolute inset-0" />
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-4 text-center">
            {hoveredHolding ? (
              <>
                <span className="text-[14px] font-semibold leading-none text-text">{hoverRow}</span>
                <span className="mt-1 max-w-[220px] truncate text-[10px] leading-none text-faint">{hoveredHolding.full_name}</span>
                <span className="mt-1.5 text-[20px] font-bold leading-none tabular-nums text-text">
                  {((exposureValue(hoveredHolding) / (allocationTotal || 1)) * 100).toFixed(2)}%
                </span>
                <span className={`mt-2 text-[12px] leading-none text-faint ${hidden ? 'masked' : ''}`}>{fmtUSDFull(exposureValue(hoveredHolding), hidden)}</span>
                <span className="mt-1 text-[11px] leading-none text-faint">
                  {hoveredHolding.ticker !== 'CASH' && <span>Qty {fmtQty(hoveredHolding.quantity)} · </span>}
                  {hoveredHolding.mark_price != null && <span>Price {fmtUSDFull(hoveredHolding.mark_price, hidden)}</span>}
                </span>
              </>
            ) : (
              <>
                <span className="text-[12px] uppercase tracking-wide text-faint">{mode} exposure</span>
                <span className={`mt-1 text-[20px] font-bold tabular-nums text-text ${hidden ? 'masked' : ''}`}>{fmtUSD(allocationTotal, hidden)}</span>
                <span className="mt-2 text-[11px] leading-none text-faint">
                  {rows.length} {rows.length === 1 ? 'position' : 'positions'}
                </span>
              </>
            )}
          </div>
        </div>

        <div className="hidden min-w-0 flex-1 overflow-x-auto scroll-thin xl:block">
          <table className="w-full min-w-[780px] table-fixed border-collapse text-[12px]">
            <colgroup>
              <col className="w-[23.25%]" /><col className="w-[15.75%]" /><col className="w-[10.9%]" /><col className="w-[8.9%]" />
              <col className="w-[13.7%]" /><col className="w-[8.5%]" /><col className="w-[6.75%]" /><col className="w-[12.25%]" />
            </colgroup>
            <thead>
              <tr className="text-[10px] font-medium uppercase tracking-wide text-faint">
                <Th label="Holding" align="left" active={sortKey === 'symbol'} onClick={() => onSort('symbol')} />
                <Th label="Exposure" align="right" active={sortKey === 'value'} onClick={() => onSort('value')} />
                <Th label="Day P/L" align="right" active={sortKey === 'day_pnl'} onClick={() => onSort('day_pnl')} />
                <Th label="Day%" align="right" active={sortKey === 'day_pct'} onClick={() => onSort('day_pct')} />
                <Th label="Allocation" align="right" /><Th label="Target" align="right" /><Th label="Drift" align="right" /><Th label="Action" align="right" />
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => {
                const sym = displaySymbol(h)
                const cur = curPcts[sym] ?? 0
                const tgt = tgtPct(sym)
                const { driftPp, action } = rebalanceMetrics(mode, cur, tgt, allocationTotal)
                const active = hoverRow === sym
                return (
                  <tr
                    key={`${h.account_id}-${h.ticker}`}
                    onMouseEnter={() => highlightSector(sym)}
                    onMouseLeave={() => highlightSector(null)}
                    className={`group border-b border-border/60 last:border-0 transition-colors ${active ? 'bg-surface-2/80' : 'hover:bg-surface-2/40'}`}
                  >
                    <Td align="left">
                      <div className="flex items-center gap-1.5">
                        <span className="h-2 w-2 shrink-0 rounded-[2px]" style={{ background: slices.find((s) => s.name === sym)?.color ?? NEUTRAL_GRAY }} />
                        <span className="font-semibold text-text">{sym}</span>
                        <span className={`rounded-full px-1.5 py-px text-[9px] font-semibold tracking-wide ${CLASS_TONE[h.asset_class] ?? 'bg-faint/10 text-muted'}`}>{h.asset_class}</span>
                      </div>
                    </Td>
                    <Td align="right" className={`font-semibold text-text ${hidden ? 'masked' : ''}`}>{fmtUSDFull(exposureValue(h), hidden)}</Td>
                    <Td align="right" className={`font-medium ${tone(h.day_pnl)} ${hidden ? 'masked' : ''}`}>{h.day_pnl >= 0 ? '+' : ''}{fmtUSDFull(h.day_pnl, hidden)}</Td>
                    <Td align="right" className={h.ticker === 'CASH' ? 'text-faint' : tone(positionDayPct(h))}>
                      {!h.prev_close_price ? '—' : `${positionDayPct(h) >= 0 ? '+' : ''}${positionDayPct(h).toFixed(2)}%`}
                    </Td>
                    <Td align="right">
                      <div className="flex items-center justify-end gap-1">
                        <div className="h-1 w-8 overflow-hidden rounded-full bg-surface-2"><div className={`h-full rounded-full ${mode === 'long' ? 'bg-accent/70' : 'bg-neg/70'}`} style={{ width: `${Math.min(cur, 100)}%` }} /></div>
                        <span className="w-10 tabular-nums text-muted">{cur.toFixed(1)}%</span>
                      </div>
                    </Td>
                    <Td align="right">{editing ? <TargetInput symbol={sym} value={edits[sym] ?? ''} onChange={(value) => setEdits((prev) => ({ ...prev, [sym]: value }))} compact /> : <span className="font-medium text-text">{tgt.toFixed(1)}%</span>}</Td>
                    <Td align="right" className={Math.abs(driftPp) < 0.05 ? 'text-faint' : 'text-muted'}>{driftPp >= 0 ? '+' : ''}{driftPp.toFixed(1)}</Td>
                    <Td align="right" className={`font-medium ${action ? action.tone : 'text-faint'}`}>{action ? `${action.label} ${fmtUSD(action.amt, hidden)}` : '—'}</Td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className="grid min-w-0 flex-1 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:hidden">
          {rows.map((h) => {
            const sym = displaySymbol(h)
            const cur = curPcts[sym] ?? 0
            const tgt = tgtPct(sym)
            const { driftPp, action } = rebalanceMetrics(mode, cur, tgt, allocationTotal)
            return (
              <div key={`${h.account_id}-${h.ticker}-mobile`} className="rounded-[12px] border border-border/70 bg-surface-2/35 p-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: slices.find((s) => s.name === sym)?.color ?? NEUTRAL_GRAY }} />
                      <span className="font-semibold text-text">{sym}</span>
                      <span className={`rounded-full px-1.5 py-px text-[10px] font-semibold tracking-wide ${CLASS_TONE[h.asset_class] ?? 'bg-faint/10 text-muted'}`}>{h.asset_class}</span>
                    </div>
                    <div className="mt-1 truncate text-[12px] text-muted">{h.full_name}</div>
                  </div>
                  <div className={`shrink-0 text-right text-[15px] font-semibold tabular-nums text-text ${hidden ? 'masked' : ''}`}>{fmtUSDFull(exposureValue(h), hidden)}</div>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-border/60 pt-3">
                  <MobileMetric label="Day P/L"><span className={`font-medium ${tone(h.day_pnl)} ${hidden ? 'masked' : ''}`}>{h.day_pnl >= 0 ? '+' : ''}{fmtUSDFull(h.day_pnl, hidden)}<span className="ml-1 text-[11px] max-[350px]:ml-0 max-[350px]:block max-[350px]:text-[10px]">{h.prev_close_price ? `(${positionDayPct(h) >= 0 ? '+' : ''}${positionDayPct(h).toFixed(2)}%)` : ''}</span></span></MobileMetric>
                  <MobileMetric label="Allocation / drift"><span className="text-text">{cur.toFixed(1)}%</span><span className="ml-1 text-[11px] text-muted">({driftPp >= 0 ? '+' : ''}{driftPp.toFixed(1)}pp)</span></MobileMetric>
                  <MobileMetric label="Target">{editing ? <TargetInput symbol={sym} value={edits[sym] ?? ''} onChange={(value) => setEdits((prev) => ({ ...prev, [sym]: value }))} /> : <span className="font-medium text-text">{tgt.toFixed(1)}%</span>}</MobileMetric>
                  <MobileMetric label="Action"><span className={`font-medium ${action ? action.tone : 'text-faint'}`}>{action ? `${action.label} ${fmtUSD(action.amt, hidden)}` : '—'}</span></MobileMetric>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function ExposureOverview({
  mode,
  portfolio,
  exposures,
  hidden,
}: {
  mode: Extract<ExposureMode, 'gross' | 'net'>
  portfolio: Portfolio
  exposures: ExposureSummary
  hidden: boolean
}) {
  const breakdown = useMemo(() => exposureByInstrument(portfolio.holdings), [portfolio.holdings])
  const { elRef } = useEChart(
    () => exposureBarOption(breakdown, mode, hidden),
    [breakdown, mode, hidden],
  )
  const longShare = exposures.gross ? exposures.long / exposures.gross : 0
  const offset = exposures.gross ? 1 - Math.abs(exposures.net) / exposures.gross : 0
  const metrics = mode === 'gross'
    ? [
        { label: 'Gross exposure', value: fmtUSD(exposures.gross, hidden), tone: 'text-text' },
        { label: 'Gross / NAV', value: ratioLabel(exposures.gross_to_nav), tone: leverageTone(exposures.gross_to_nav) },
        { label: 'Long share', value: `${(longShare * 100).toFixed(1)}%`, tone: 'text-accent' },
        { label: 'Short share', value: `${((1 - longShare) * 100).toFixed(1)}%`, tone: 'text-neg' },
      ]
    : [
        { label: 'Net exposure', value: fmtUSD(exposures.net, hidden), tone: exposures.net < 0 ? 'text-neg' : 'text-text' },
        { label: 'Net / NAV', value: ratioLabel(exposures.net_to_nav), tone: 'text-text' },
        { label: 'Gross offset', value: `${Math.max(0, offset * 100).toFixed(1)}%`, tone: 'text-accent' },
        { label: 'Direction', value: exposures.net > 0 ? 'Long bias' : exposures.net < 0 ? 'Short bias' : 'Neutral', tone: exposures.net < 0 ? 'text-neg' : 'text-text' },
      ]

  return (
    <div className="p-4 sm:p-6">
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {metrics.map((metric) => (
          <div key={metric.label} className="rounded-[12px] border border-border/70 bg-surface-2/35 px-3.5 py-3">
            <div className="text-[10px] font-medium uppercase tracking-wide text-faint">{metric.label}</div>
            <div className={`mt-1.5 text-[18px] font-semibold tabular-nums ${metric.tone} ${hidden && metric.value.includes('$') ? 'masked' : ''}`}>{metric.value}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(440px,0.9fr)]">
        <div className="rounded-[14px] border border-border/70 p-3 sm:p-4">
          <div className="flex items-center justify-between gap-3 max-[359px]:flex-col max-[359px]:items-start max-[359px]:gap-2">
            <div>
              <h3 className="text-[12px] font-semibold text-text">Exposure by instrument</h3>
              <p className="mt-1 text-[10px] text-faint">{mode === 'gross' ? 'Long and short magnitudes shown side by side' : 'Long is positive; short is negative'}</p>
            </div>
            <div className="flex items-center gap-3 text-[10px] text-faint">
              <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-[2px] bg-accent" />Long</span>
              <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-[2px] bg-neg" />Short</span>
            </div>
          </div>
          <div ref={elRef} className="mt-2 w-full" style={{ height: `${Math.max(300, Math.min(520, breakdown.length * 34))}px` }} />
        </div>

        <div className="min-w-0 overflow-hidden rounded-[14px] border border-border/70 p-3 sm:p-4">
          <h3 className="text-[12px] font-semibold text-text">Exposure ledger</h3>
          <div className="mt-3 max-h-[520px] min-w-0 overflow-auto scroll-thin">
            <table className="w-full min-w-[480px] border-collapse text-[11px]">
              <thead className="sticky top-0 z-10 bg-surface"><tr className="border-b border-border text-[9px] uppercase tracking-wide text-faint"><Th label="Holding" align="left" /><Th label="Long" align="right" /><Th label="Short" align="right" /><Th label="Gross" align="right" /><Th label="Net" align="right" /></tr></thead>
              <tbody>
                {breakdown.map((row) => (
                  <tr key={row.symbol} className="border-b border-border/60 last:border-0">
                    <Td align="left">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-text">{row.symbol}</span>
                        <span className={`rounded-full px-1.5 py-px text-[9px] font-semibold tracking-wide ${CLASS_TONE[row.assetClass] ?? 'bg-faint/10 text-muted'}`}>{row.assetClass}</span>
                      </div>
                      <div className="mt-0.5 max-w-[160px] truncate text-[9px] text-faint">{row.fullName}</div>
                    </Td>
                    <Td align="right" className={`text-text ${hidden ? 'masked' : ''}`}>{fmtUSDFull(row.long, hidden)}</Td>
                    <Td align="right" className={`text-text ${hidden ? 'masked' : ''}`}>{fmtUSDFull(row.short, hidden)}</Td>
                    <Td align="right" className={`font-semibold text-text ${hidden ? 'masked' : ''}`}>{fmtUSDFull(row.gross, hidden)}</Td>
                    <Td align="right" className={`${row.net < 0 ? 'text-neg' : 'text-text'} ${hidden ? 'masked' : ''}`}>{fmtUSDFull(row.net, hidden)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

interface ExposureBreakdown {
  symbol: string
  fullName: string
  assetClass: string
  long: number
  short: number
  gross: number
  net: number
}

function exposureByInstrument(holdings: Holding[]): ExposureBreakdown[] {
  const groups = new Map<string, ExposureBreakdown>()
  for (const holding of holdings) {
    const symbol = displaySymbol(holding)
    const group = groups.get(symbol) ?? {
      symbol,
      fullName: holding.full_name,
      assetClass: holding.asset_class || 'OTHER',
      long: 0,
      short: 0,
      gross: 0,
      net: 0,
    }
    if (holding.market_value >= 0) group.long += holding.market_value
    else group.short += Math.abs(holding.market_value)
    group.gross = group.long + group.short
    group.net = group.long - group.short
    groups.set(symbol, group)
  }
  return [...groups.values()].sort((a, b) => b.gross - a.gross)
}

function exposureBarOption(rows: ExposureBreakdown[], mode: 'gross' | 'net', hidden: boolean): echarts.EChartsCoreOption {
  const t = getChartTheme()
  const ordered = [...rows].reverse()
  return {
    grid: { left: 12, right: 12, top: 12, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: t.text, fontSize: 11 },
      formatter: (params: Array<{ seriesName: string; value: number; marker: string }>) => {
        const items = Array.isArray(params) ? params : []
        return items.map((item) => `${item.marker}${item.seriesName}: ${hidden ? '••••' : fmtUSDFull(Math.abs(item.value))}`).join('<br/>')
      },
    },
    xAxis: {
      type: 'value',
      axisLabel: {
        color: t.faint,
        fontSize: 9,
        hideOverlap: true,
        formatter: (value: number) => hidden ? '••' : compactAxisValue(value),
      },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: t.splitLine } },
    },
    yAxis: {
      type: 'category',
      data: ordered.map((row) => row.symbol),
      axisLabel: { color: t.muted, fontSize: 10 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        name: 'Long', type: 'bar', data: ordered.map((row) => row.long),
        barMaxWidth: 18, itemStyle: { color: t.accent, borderRadius: mode === 'gross' ? [4, 4, 4, 4] : [0, 4, 4, 0] },
      },
      {
        name: 'Short', type: 'bar', data: ordered.map((row) => mode === 'net' ? -row.short : row.short),
        barMaxWidth: 18, itemStyle: { color: t.neg, borderRadius: mode === 'gross' ? [4, 4, 4, 4] : [4, 0, 0, 4] },
      },
    ],
    animationDuration: 600,
    animationEasing: 'cubicOut',
  } as echarts.EChartsCoreOption
}

/**
 * Consolidated views show one row per instrument within each directional
 * book. Long and short lots are intentionally aggregated separately so an
 * offsetting position in another account does not make gross risk disappear.
 */
function aggregateDirectionalPositions(holdings: Holding[], aggregate: boolean): Holding[] {
  if (!aggregate) return holdings

  const groups = new Map<string, Holding>()
  for (const holding of holdings) {
    const symbol = displaySymbol(holding)
    const current = groups.get(symbol)
    if (!current) {
      groups.set(symbol, { ...holding, account_id: 'ALL' })
      continue
    }
    current.quantity += holding.quantity
    current.market_value += holding.market_value
    current.day_pnl += holding.day_pnl
    current.unrealized_pnl += holding.unrealized_pnl
    current.cost_basis = sumNullable(current.cost_basis, holding.cost_basis)
    current.prev_close_quantity = sumNullable(current.prev_close_quantity, holding.prev_close_quantity)
    current.xml_percent_of_nav = null
  }
  return [...groups.values()]
}

function sumNullable(a: number | null, b: number | null): number | null {
  if (a == null && b == null) return null
  return (a ?? 0) + (b ?? 0)
}

function deriveExposureSummary(holdings: Holding[], nav: number): ExposureSummary {
  const long = holdings.reduce((sum, h) => sum + Math.max(h.market_value, 0), 0)
  const short = holdings.reduce((sum, h) => sum + Math.abs(Math.min(h.market_value, 0)), 0)
  const gross = long + short
  const net = long - short
  const denominator = Math.abs(nav)
  return {
    long,
    short,
    gross,
    net,
    gross_to_nav: denominator ? gross / denominator : null,
    net_to_nav: denominator ? net / denominator : null,
  }
}

function exposureTabValue(mode: ExposureMode, exposures: ExposureSummary): number {
  return exposures[mode]
}

function exposureValue(holding: Holding): number {
  return Math.abs(holding.market_value)
}

function allocationWeights(holdings: Holding[], total: number): Record<string, number> {
  const result: Record<string, number> = {}
  if (total <= 0 || holdings.length === 0) return result
  const parts = holdings.map((holding, index) => {
    const exactTenths = (exposureValue(holding) / total) * 1000
    const floorTenths = Math.floor(exactTenths)
    return { symbol: displaySymbol(holding), index, floorTenths, remainder: exactTenths - floorTenths }
  })
  let unitsLeft = 1000 - parts.reduce((sum, part) => sum + part.floorTenths, 0)
  parts.sort((a, b) => b.remainder - a.remainder || a.index - b.index)
  for (const part of parts) {
    if (unitsLeft <= 0) break
    part.floorTenths += 1
    unitsLeft -= 1
  }
  for (const part of parts) result[part.symbol] = part.floorTenths / 10
  return result
}

function positionDayPct(holding: Holding): number {
  if (!holding.prev_close_price || !holding.mark_price) return 0
  const priceMove = ((holding.mark_price - holding.prev_close_price) / holding.prev_close_price) * 100
  return holding.market_value < 0 ? -priceMove : priceMove
}

function targetStorageKey(mode: DirectionalMode, symbol: string): string {
  return mode === 'short' ? `SHORT:${symbol}` : symbol
}

function rebalanceMetrics(mode: DirectionalMode, current: number, target: number, allocationValue: number) {
  const driftPp = round1(current - target)
  if (Math.abs(driftPp) < 0.05) return { driftPp, action: null }
  const trade = (allocationValue * -driftPp) / 100
  if (mode === 'short') {
    return {
      driftPp,
      action: trade < 0
        ? { label: 'Cover', amt: -trade, tone: 'text-pos' }
        : { label: 'Short', amt: trade, tone: 'text-neg' },
    }
  }
  return {
    driftPp,
    action: trade < 0
      ? { label: 'Sell', amt: -trade, tone: 'text-neg' }
      : { label: 'Buy', amt: trade, tone: 'text-pos' },
  }
}

function ratioLabel(value: number | null): string {
  return value == null ? '—' : `${value.toFixed(2)}×`
}

function leverageTone(value: number | null): string {
  return value != null && value > 1 ? 'text-warn' : 'text-text'
}

function tone(value: number) {
  return value > 0 ? 'text-pos' : value < 0 ? 'text-neg' : 'text-faint'
}

function Th({ label, align, active, onClick }: { label: string; align: 'left' | 'right'; active?: boolean; onClick?: () => void }) {
  return <th className={`whitespace-nowrap border-b border-border px-1.5 pb-2 font-medium ${align === 'right' ? 'text-right' : 'text-left'} ${onClick ? 'cursor-pointer select-none hover:text-text' : ''} ${active ? 'text-text' : ''}`} onClick={onClick}>{label}{active && <span className="ml-0.5">↕</span>}</th>
}

function Td({ align, className = '', children }: { align: 'left' | 'right'; className?: string; children: React.ReactNode }) {
  return <td className={`h-[43px] px-1.5 py-0 tabular-nums text-muted ${align === 'right' ? 'text-right' : ''} ${className}`}>{children}</td>
}

function MobileMetric({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="min-w-0"><div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-faint max-[350px]:whitespace-nowrap max-[350px]:text-[9px] max-[350px]:tracking-normal">{label}</div><div className="text-[14px] leading-snug tabular-nums text-muted max-[350px]:text-[12px]">{children}</div></div>
}

function compactAxisValue(value: number): string {
  const absolute = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (absolute >= 1_000_000) return `${sign}${(absolute / 1_000_000).toFixed(absolute >= 10_000_000 ? 0 : 1)}M`
  if (absolute >= 1_000) return `${sign}${(absolute / 1_000).toFixed(absolute >= 10_000 ? 0 : 1)}K`
  return `${Math.round(value)}`
}

function TargetInput({ symbol, value, onChange, compact = false }: { symbol: string; value: string; onChange: (value: string) => void; compact?: boolean }) {
  return (
    <label className="inline-flex items-center gap-1">
      <input
        aria-label={`${symbol} target allocation`}
        type="number"
        inputMode="decimal"
        min={0}
        step={0.1}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={(event) => {
          const parsed = parseFloat(event.target.value)
          if (Number.isFinite(parsed)) onChange(String(round1(parsed)))
        }}
        className={compact
          ? 'w-14 rounded-[6px] border border-accent/50 bg-accent/5 px-1.5 py-0.5 text-right text-[12px] tabular-nums text-text outline-none focus:border-accent focus:ring-2 focus:ring-accent/15'
          : 'h-10 w-20 rounded-[8px] border border-accent/50 bg-surface px-2 text-right text-[15px] tabular-nums text-text outline-none focus:border-accent focus:ring-2 focus:ring-accent/15'}
      />
      <span className="text-muted">%</span>
    </label>
  )
}

function EditIcon() {
  return <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M10.8 2.2a1.4 1.4 0 0 1 2 2L5.1 11.9l-2.6.6.6-2.6 7.7-7.7Z" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

function ExposureIcon({ mode }: { mode: DirectionalMode }) {
  return <svg className="h-5 w-5" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d={mode === 'long' ? 'M4 14 9 9l3 3 4-6' : 'M4 6l5 5 3-3 4 6'} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
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
      formatter: (params: { name: string; value: number; percent: number; data: { full_name?: string; day_pnl?: number } }) => {
        const usd = hidden ? '••••' : fmtUSDFull(params.value)
        const fullName = params.data?.full_name ? `<div style="color:${t.faint};font-size:10px;margin-top:2px">${params.data.full_name}</div>` : ''
        const dayPnl = params.data?.day_pnl
        const day = dayPnl != null && dayPnl !== 0 ? `<div style="margin-top:2px;color:${dayPnl >= 0 ? t.pos : t.neg}">${dayPnl >= 0 ? '+' : ''}${hidden ? '••••' : fmtUSDFull(dayPnl)} today</div>` : ''
        return `<div style="font-weight:600">${params.name}</div>${fullName}<div style="margin-top:4px">${usd} · ${params.percent.toFixed(2)}%</div>${day}`
      },
    },
    series: [{
      type: 'pie', radius: ['62%', '88%'], center: ['50%', '50%'], padAngle: 2,
      itemStyle: { borderRadius: 5, borderColor: t.surface, borderWidth: 3 },
      label: { show: false }, labelLine: { show: false },
      emphasis: { scale: true, scaleSize: 6, itemStyle: chartEmphasisItemStyle },
      startAngle: 90,
      data: slices.map((slice) => ({ ...slice, itemStyle: { color: slice.color } })),
    }],
    animationDuration: 700,
    animationEasing: 'cubicOut',
  } as echarts.EChartsCoreOption
}
