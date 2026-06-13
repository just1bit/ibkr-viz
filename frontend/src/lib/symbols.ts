import type { Holding } from './types'

/**
 * Compact display symbol. Stocks/ETFs use the ticker as-is; options collapse
 * the OCC symbol ("BRKB  270115C00500000") into "BRK B 500C".
 */
export function displaySymbol(h: Holding): string {
  if (h.put_call && h.underlying_symbol) {
    return `${h.underlying_symbol} ${trimNum(h.strike ?? 0)}${h.put_call}`
  }
  return h.ticker
}

/** Option contract terms line: "Call 500 · Exp 2027-01-15 · 583d · ×100". */
export function optionTerms(h: Holding, reportDate: string): string | null {
  if (!h.put_call) return null
  const kind = h.put_call === 'C' ? 'Call' : 'Put'
  const parts = [`${kind} ${trimNum(h.strike ?? 0)}`]
  if (h.expiry) {
    parts.push(`Exp ${h.expiry}`)
    const dte = daysBetween(reportDate, h.expiry)
    if (dte !== null) parts.push(`${dte}d`)
  }
  if (h.multiplier && h.multiplier !== 1) parts.push(`×${trimNum(h.multiplier)}`)
  return parts.join(' · ')
}

function trimNum(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(2)
}

function daysBetween(from: string, to: string): number | null {
  const a = Date.parse(from)
  const b = Date.parse(to)
  if (Number.isNaN(a) || Number.isNaN(b)) return null
  return Math.round((b - a) / 86_400_000)
}
