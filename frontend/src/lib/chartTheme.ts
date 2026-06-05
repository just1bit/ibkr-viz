// Reads the current semantic palette from CSS variables so ECharts (which needs
// concrete color strings) stays in sync with the active light/dark theme.

function readVar(name: string): string {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim()
  // tokens are stored as "r g b" triples
  return `rgb(${raw.split(/\s+/).join(' ')})`
}

function rgba(name: string, alpha: number): string {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim()
  return `rgba(${raw.split(/\s+/).join(', ')}, ${alpha})`
}

export interface ChartTheme {
  text: string
  muted: string
  faint: string
  border: string
  surface: string
  accent: string
  tooltipBg: string
  tooltipBorder: string
  splitLine: string
}

// Curated categorical palette — works on both light and dark backgrounds.
const PALETTE_DARK = [
  '#2dd4bf', '#60a5fa', '#f0a868', '#a78bfa', '#34d399',
  '#f472b6', '#fbbf24', '#22d3ee', '#fb7185', '#818cf8',
  '#4ade80', '#e879f9',
]
const PALETTE_LIGHT = [
  '#0d9488', '#2563eb', '#d97706', '#7c3aed', '#059669',
  '#db2777', '#ca8a04', '#0891b2', '#e11d48', '#4f46e5',
  '#16a34a', '#c026d3',
]

export function getChartTheme(): ChartTheme {
  const isDark = document.documentElement.classList.contains('dark')
  return {
    text: readVar('--text'),
    muted: readVar('--text-muted'),
    faint: readVar('--text-faint'),
    border: readVar('--border'),
    surface: readVar('--surface'),
    accent: readVar('--accent'),
    tooltipBg: isDark ? 'rgba(18,18,21,0.96)' : 'rgba(255,255,255,0.98)',
    tooltipBorder: readVar('--border-strong'),
    splitLine: rgba('--border', isDark ? 0.6 : 1),
  }
}

export function paletteFor(index: number): string {
  const isDark = document.documentElement.classList.contains('dark')
  const p = isDark ? PALETTE_DARK : PALETTE_LIGHT
  return p[index % p.length]
}
