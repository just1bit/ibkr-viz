import { useEffect, useRef } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import { echarts } from '../lib/echarts'
import { useTheme } from './useTheme'

type EChartsType = ReturnType<typeof echarts.init>

/**
 * Mounts an ECharts instance on a div and re-applies `option` whenever it (or
 * the active theme) changes. Handles resize + cleanup. The `build` callback
 * receives the live echarts namespace so callers can use gradients etc.
 */
export function useEChart(
  build: (ec: typeof echarts) => EChartsCoreOption,
  deps: unknown[],
) {
  const elRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const { theme } = useTheme()

  useEffect(() => {
    if (!elRef.current) return
    const chart = echarts.init(elRef.current, undefined, { renderer: 'canvas' })
    chartRef.current = chart
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(elRef.current)
    return () => {
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    chart.setOption(build(echarts), true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, ...deps])

  return { elRef, chartRef }
}
