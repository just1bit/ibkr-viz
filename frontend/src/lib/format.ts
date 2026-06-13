export function fmtUSD(v: number, hidden = false): string {
  if (hidden) return '••••'
  const abs = Math.abs(v)
  let s: string
  if (abs >= 1e6) s = '$' + (abs / 1e6).toFixed(2) + 'M'
  else if (abs >= 1e3) s = '$' + (abs / 1e3).toFixed(2) + 'K'
  else s = '$' + abs.toFixed(2)
  return (v < 0 ? '-' : '') + s
}

/** Full-precision dollars for tables: $35,235.72 (no K/M compression). */
export function fmtUSDFull(v: number, hidden = false): string {
  if (hidden) return '••••'
  const abs = Math.abs(v)
  const s =
    '$' + abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return (v < 0 ? '-' : '') + s
}

export function fmtPct(v: number): string {
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}

/** Quantity: integers without decimals, fractional amounts with up to 4. */
export function fmtQty(v: number): string {
  return v.toLocaleString('en-US', { maximumFractionDigits: 4 })
}
