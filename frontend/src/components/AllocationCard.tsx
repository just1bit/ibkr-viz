import { useMemo, useState } from 'react'
import type * as echarts from 'echarts/core'
import type { AllocationSlice, DonutView, Portfolio } from '../lib/types'
import { fmtUSD } from '../lib/format'
import { getChartTheme, paletteFor } from '../lib/chartTheme'
import { useEChart } from '../hooks/useEChart'
import { Segmented } from './Segmented'

interface Props {
  portfolio: Portfolio
  hidden: boolean
}

const VIEWS: { value: DonutView; label: string }[] = [
  { value: 'ticker', label: 'Holdings' },
  { value: 'asset_class', label: 'Asset class' },
]

export function AllocationCard({ portfolio, hidden }: Props) {
  const [view, setView] = useState<DonutView>('ticker')
  const [hover, setHover] = useState<string | null>(null)

  const slices = useMemo(() => buildSlices(portfolio, view), [portfolio, view])
  const total = slices.reduce((sum, s) => sum + s.value, 0)

  const { elRef, chartRef } = useEChart(
    () => donutOption(slices, hidden),
    [slices, hidden],
  )

  function highlight(name: string | null) {
    setHover(name)
    const chart = chartRef.current
    if (!chart) return
    chart.dispatchAction({ type: 'downplay', seriesIndex: 0 })
    if (name) chart.dispatchAction({ type: 'highlight', seriesIndex: 0, name })
  }

  return (
    <div className="flex h-full flex-col rounded-[var(--radius-lg)] border border-border bg-surface shadow-[var(--shadow)]">
      <div className="flex items-center justify-between gap-3 px-5 pt-5 sm:px-6">
        <h2 className="text-[15px] font-semibold tracking-tight text-text">
          Allocation
        </h2>
        <Segmented options={VIEWS} value={view} onChange={setView} size="sm" />
      </div>

      <div className="flex flex-1 flex-col gap-2 p-3 sm:flex-row sm:p-4">
        <div className="relative min-h-[300px] flex-1">
          <div ref={elRef} className="absolute inset-0" />
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <div className="text-[11px] uppercase tracking-wide text-faint">
              {hover ?? 'Total'}
            </div>
            <div
              className={`mt-1 text-[20px] font-semibold tnum text-text ${hidden ? 'masked' : ''}`}
            >
              {hover
                ? (() => {
                    const s = slices.find((x) => x.name === hover)
                    return s ? `${((s.value / total) * 100).toFixed(1)}%` : ''
                  })()
                : fmtUSD(total, hidden)}
            </div>
          </div>
        </div>

        <div className="scroll-thin flex max-h-[340px] w-full flex-col gap-0.5 overflow-y-auto sm:w-[220px]">
          {slices.map((s) => {
            const pct = total > 0 ? (s.value / total) * 100 : 0
            const active = hover === s.name
            return (
              <button
                key={s.name}
                onMouseEnter={() => highlight(s.name)}
                onMouseLeave={() => highlight(null)}
                className={`flex items-center gap-2.5 rounded-[8px] px-2.5 py-1.5 text-left transition-colors ${
                  active ? 'bg-surface-2' : 'hover:bg-surface-2'
                }`}
              >
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                  style={{ background: s.color }}
                />
                <span className="flex-1 truncate text-[12px] font-medium text-text">
                  {s.name}
                </span>
                <span
                  className={`tnum text-[11px] text-muted ${hidden ? 'masked' : ''}`}
                >
                  {fmtUSD(s.value, hidden)}
                </span>
                <span className="w-11 text-right tnum text-[11px] font-medium text-faint">
                  {pct.toFixed(1)}%
                </span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function buildSlices(p: Portfolio, view: DonutView): AllocationSlice[] {
  if (view === 'asset_class') return recolor(p.asset_class_summary)

  const sorted = [...p.ticker_summary].sort((a, b) => b.value - a.value)
  const tot = sorted.reduce((s, d) => s + d.value, 0)
  const main: AllocationSlice[] = []
  let others = 0
  sorted.forEach((h) => {
    if ((h.value / tot) * 100 >= 0.5) main.push(h)
    else others += h.value
  })
  const out: AllocationSlice[] = main.map((s, i) => ({ ...s, color: sliceColor(s.name, i) }))
  if (others > 0) {
    out.push({
      name: 'Others',
      value: Math.round(others),
      color: NEUTRAL_GRAY,
    })
  }
  return out
}

const NEUTRAL_GRAY = '#8b8b94'

// Cash gets a fixed neutral gray in every view so it reads as "uninvested".
function sliceColor(name: string, i: number): string {
  return name === 'CASH' || name === 'Cash' ? NEUTRAL_GRAY : paletteFor(i)
}

function recolor(items: AllocationSlice[]): AllocationSlice[] {
  return items.map((s, i) => ({ ...s, color: sliceColor(s.name, i) }))
}

function donutOption(
  slices: AllocationSlice[],
  hidden: boolean,
): echarts.EChartsCoreOption {
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
        const fn = p.data?.full_name
          ? `<div style="color:${t.faint};font-size:10px;margin-top:2px">${p.data.full_name}</div>`
          : ''
        const dp = p.data?.day_pnl
        const day =
          dp != null && dp !== 0
            ? `<div style="margin-top:2px;font-variant-numeric:tabular-nums;color:${dp >= 0 ? '#22a06b' : '#e5484d'}">${dp >= 0 ? '+' : ''}${hidden ? '••••' : '$' + dp.toLocaleString()} today</div>`
            : ''
        return `<div style="font-weight:600">${p.name}</div>${fn}<div style="margin-top:4px;font-variant-numeric:tabular-nums">${usd} · ${p.percent.toFixed(2)}%</div>${day}`
      },
    },
    series: [
      {
        type: 'pie',
        radius: ['62%', '88%'],
        center: ['50%', '50%'],
        padAngle: 2,
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 5,
          borderColor: t.surface,
          borderWidth: 3,
        },
        label: { show: false },
        labelLine: { show: false },
        emphasis: {
          scale: true,
          scaleSize: 6,
          itemStyle: {
            shadowBlur: 14,
            shadowColor: 'rgba(0,0,0,0.25)',
          },
        },
        startAngle: 90,
        data: slices.map((d) => ({
          name: d.name,
          value: d.value,
          full_name: d.full_name,
          day_pnl: d.day_pnl,
          itemStyle: { color: d.color },
        })),
      },
    ],
    animationDuration: 700,
    animationEasing: 'cubicOut',
  } as echarts.EChartsCoreOption
}
