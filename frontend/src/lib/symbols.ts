import type { Holding } from './types'

/**
 * Compact display symbol. Stocks/ETFs use the ticker as-is; options collapse
 * the OCC symbol ("BRKB  270115C00500000") into "BRKB 270115C500".
 */
export function displaySymbol(h: Holding): string {
  const occSymbol = displayTicker(h.ticker)
  if (occSymbol !== h.ticker) return occSymbol

  if (h.put_call && h.underlying_symbol && h.expiry) {
    const expiry = compactExpiry(h.expiry)
    if (expiry) {
      const underlying = h.underlying_symbol.replace(/\s+/g, '')
      return `${underlying} ${expiry}${h.put_call.toUpperCase()}${trimStrike(h.strike ?? 0)}`
    }
  }
  return h.ticker
}

/** Format a raw ticker when option metadata is not available (for example MTM rows). */
export function displayTicker(ticker: string): string {
  const candidate = ticker.trim()
  const padded = candidate.match(/^(.{1,6})(\d{6})([CP])(\d{8})$/i)
  const unpadded = candidate.match(/^([A-Z0-9.]{1,6})\s+(\d{6})([CP])(\d{8})$/i)
  const match = padded ?? unpadded
  if (!match) return ticker

  const underlying = match[1].replace(/\s+/g, '')
  const strike = Number(match[4]) / 1000
  return `${underlying} ${match[2]}${match[3].toUpperCase()}${trimStrike(strike)}`
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

function trimStrike(v: number): string {
  return String(Number(v.toFixed(3)))
}

function compactExpiry(expiry: string): string | null {
  const digits = expiry.replace(/\D/g, '')
  if (digits.length === 8) return digits.slice(2)
  if (digits.length === 6) return digits
  return null
}

function daysBetween(from: string, to: string): number | null {
  const a = Date.parse(from)
  const b = Date.parse(to)
  if (Number.isNaN(a) || Number.isNaN(b)) return null
  return Math.round((b - a) / 86_400_000)
}
