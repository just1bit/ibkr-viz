import { useMemo } from 'react'
import type * as echarts from 'echarts/core'
import type { Holding, Portfolio } from '../lib/types'
import { fmtUSD, fmtUSDFull } from '../lib/format'
import { chartEmphasisItemStyle, getChartTheme } from '../lib/chartTheme'
import { useEChart } from '../hooks/useEChart'
import { displaySymbol } from '../lib/symbols'

interface Props {
  portfolio: Portfolio
  hidden: boolean
}

interface Row {
  name: string
  fullName: string
  pnl: number
  prevClose: number | null
  close: number | null
}

/**
 * Day P&L attribution: one diverging bar per position, straight from the
 * statement's MTM performance summary. Shows at a glance which holdings
 * drove today's account-level P&L.
 */
export function DayPnlCard({ portfolio, hidden }: Props) {
  const rows = useMemo<Row[]>(
    () =>
      portfolio.holdings
        .filter((h) => h.ticker !== 'CASH')
        .map((h: Holding) => ({
          name: displaySymbol(h),
          fullName: h.full_name,
          pnl: h.day_pnl,
          prevClose: h.prev_close_price,
          close: h.mark_price,
        }))
        .sort((a, b) => b.pnl - a.pnl),
    [portfolio],
  )

  const total = portfolio.summary.total_day_pnl
  const { elRef } = useEChart(() => barOption(rows, hidden), [rows, hidden])
  const mobileChartHeight = Math.max(210, rows.length * 27 + 28)

  return (
    <div className="flex h-full flex-col rounded-[var(--radius-lg)] border border-border bg-surface shadow-[var(--shadow)]">
      <div className="flex items-center justify-between gap-3 px-5 pt-5 sm:px-6">
        <h2 className="text-[15px] font-semibold tracking-tight text-text">
          Day P/L by position
        </h2>
        <span
          className={`rounded-full px-2.5 py-1 text-[12px] font-semibold tnum ${
            total >= 0 ? 'bg-pos/10 text-pos' : 'bg-neg/10 text-neg'
          } ${hidden ? 'masked' : ''}`}
        >
          {total >= 0 ? '+' : ''}
          {fmtUSD(total, hidden)}
        </span>
      </div>
      <div
        className="relative min-h-[var(--mobile-chart-height)] flex-1 p-2 sm:min-h-[200px] sm:p-3"
        style={{ '--mobile-chart-height': `${mobileChartHeight}px` } as React.CSSProperties}
      >
        <div ref={elRef} className="absolute inset-0" />
      </div>
    </div>
  )
}

function barOption(rows: Row[], hidden: boolean): echarts.EChartsCoreOption {
  const t = getChartTheme()
  const mobile = window.innerWidth < 640
  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: t.text, fontSize: mobile ? 13 : 12 },
      extraCssText: 'border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,0.18);',
      formatter: (p: { dataIndex: number }) => {
        const r = rows[p.dataIndex]
        const pnl = hidden
          ? '••••'
          : `${r.pnl >= 0 ? '+' : ''}${fmtUSDFull(r.pnl)}`
        const px =
          r.prevClose && r.close
            ? `<div style="color:${t.faint};font-size:11px;margin-top:2px;font-variant-numeric:tabular-nums">${fmtUSDFull(r.prevClose)} → ${fmtUSDFull(r.close)} (${(((r.close - r.prevClose) / r.prevClose) * 100).toFixed(2)}%)</div>`
            : ''
        return `<div style="font-weight:600">${r.name}</div><div style="color:${t.faint};font-size:10px">${r.fullName}</div><div style="margin-top:4px;font-variant-numeric:tabular-nums;color:${r.pnl >= 0 ? t.pos : t.neg}">${pnl}</div>${px}`
      },
    },
    grid: {
      left: 36,
      right: 76,
      top: mobile ? 6 : 12,
      bottom: mobile ? 6 : 12,
      containLabel: true,
    },
    xAxis: {
      type: 'value',
      axisLabel: { show: false },
      splitLine: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map((r) => r.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: mobile ? 12 : 11, fontWeight: 500 },
    },
    series: [
      {
        type: 'bar',
        barWidth: 16,
        data: rows.map((r) => {
          const color = r.pnl >= 0 ? t.pos : t.neg
          return {
            value: r.pnl,
            itemStyle: {
              color,
              borderRadius: 4,
            },
            emphasis: {
              // Bar emphasis does not reliably inherit a per-data-item fill
              // the way pie emphasis does. Preserve it explicitly or the bar
              // can flash and then render transparent while hovered.
              itemStyle: {
                color,
                borderColor: color,
                borderWidth: 2,
                ...chartEmphasisItemStyle,
              },
            },
            label: {
              position: 'right',
              color: t.muted,
            },
          }
        }),
        label: {
          show: true,
          fontSize: mobile ? 12 : 11,
          fontWeight: 500,
          color: t.muted,
          formatter: (p: { value: number }) =>
            hidden ? '••••' : (p.value >= 0 ? '+' : '') + fmtUSD(p.value),
        },
      },
    ],
    animationDuration: 600,
    animationEasing: 'cubicOut',
  } as echarts.EChartsCoreOption
}
