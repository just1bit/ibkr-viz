export function fmtUSD(v: number, hidden = false): string {
  if (hidden) return '••••'
  const abs = Math.abs(v)
  let s: string
  if (abs >= 1e6) s = '$' + (abs / 1e6).toFixed(2) + 'M'
  else if (abs >= 1e3) s = '$' + (abs / 1e3).toFixed(2) + 'K'
  else s = '$' + abs.toFixed(2)
  return (v < 0 ? '-' : '') + s
}

export function fmtPct(v: number): string {
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}
