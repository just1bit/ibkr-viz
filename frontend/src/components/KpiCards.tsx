import type { Portfolio } from '../lib/types'
import { fmtPct, fmtUSD } from '../lib/format'

interface Props {
  portfolio: Portfolio
  hidden: boolean
}

type Tone = 'neutral' | 'pos' | 'neg'

interface Kpi {
  label: string
  value: string
  delta?: string
  tone?: Tone
  mask?: boolean
}

export function KpiCards({ portfolio, hidden }: Props) {
  const s = portfolio.summary
  const netLiq = s.net_liquidation || s.total_value
  const dayRate = netLiq ? (s.total_day_pnl / (netLiq - s.total_day_pnl)) * 100 : 0

  const cards: Kpi[] = [
    { label: 'Net asset value', value: fmtUSD(netLiq, hidden), mask: true },
    {
      label: `Day P/L · ${portfolio.date}`,
      value: fmtPct(dayRate),
      delta: fmtUSD(s.total_day_pnl, hidden),
      tone: s.total_day_pnl >= 0 ? 'pos' : 'neg',
      mask: true,
    },
    { label: 'Market value', value: fmtUSD(s.total_value, hidden), mask: true },
    { label: 'Cash balance', value: fmtUSD(s.total_cash, hidden), mask: true },
  ]

  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
      {cards.map((c, i) => (
        <KpiCard key={c.label} kpi={c} hidden={hidden} index={i} />
      ))}
    </div>
  )
}

const toneText: Record<Tone, string> = {
  neutral: 'text-text',
  pos: 'text-pos',
  neg: 'text-neg',
}

function KpiCard({
  kpi,
  hidden,
  index,
}: {
  kpi: Kpi
  hidden: boolean
  index: number
}) {
  const tone = kpi.tone ?? 'neutral'
  const masked = kpi.mask && hidden
  return (
    <div
      className="animate-fade-up rounded-[var(--radius-md)] border border-border bg-surface p-4 shadow-[var(--shadow)]"
      style={{ animationDelay: `${index * 40}ms` }}
    >
      <div className="text-[11px] font-medium uppercase tracking-wide text-faint">
        {kpi.label}
      </div>
      <div
        className={`mt-2 text-[22px] font-semibold leading-none tnum ${toneText[tone]} ${
          masked ? 'masked' : ''
        }`}
      >
        {kpi.value}
      </div>
      {kpi.delta && (
        <div
          className={`mt-1.5 text-[12px] font-medium tnum ${toneText[tone]} ${
            masked ? 'masked' : 'opacity-80'
          }`}
        >
          {kpi.delta}
        </div>
      )}
    </div>
  )
}
