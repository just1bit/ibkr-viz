import type { Portfolio } from '../lib/types'
import { fmtPct, fmtUSD } from '../lib/format'
import { CardDate } from './CardMeta'

interface Props {
  portfolio: Portfolio
  hidden: boolean
}

export function WealthHero({ portfolio, hidden }: Props) {
  const s = portfolio.summary
  const nav = s.net_liquidation
  const previousNav = s.previous_net_liquidation
  const dayRate = previousNav ? (s.total_day_pnl / previousNav) * 100 : 0
  const pnlTone = s.total_day_pnl >= 0 ? 'text-pos' : 'text-neg'
  const pnlSurface = s.total_day_pnl >= 0
    ? 'border-pos/15 bg-pos/[0.045]'
    : 'border-neg/15 bg-neg/[0.045]'

  return (
    <div className="flex h-full min-h-[246px] flex-col rounded-[var(--radius-lg)] border border-border bg-surface p-5 shadow-[var(--shadow)] sm:min-h-0">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">Net liquidation</span>
        <CardDate date={portfolio.date} />
      </div>

      <p className={`mt-2.5 text-[32px] font-bold leading-none tracking-tight tabular-nums text-text sm:text-[34px] ${hidden ? 'masked' : ''}`}>
        {fmtUSD(nav, hidden)}
      </p>

      <div className={`mt-4 rounded-[12px] border px-3.5 py-3 ${pnlSurface}`}>
        <div className="flex items-end justify-between gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">Today</div>
            <div className={`mt-1 text-[13px] font-semibold tabular-nums ${pnlTone} ${hidden ? 'masked' : ''}`}>
              {s.total_day_pnl >= 0 ? '+' : ''}{fmtUSD(s.total_day_pnl, hidden)}
            </div>
          </div>
          <div className={`text-[26px] font-bold leading-none tabular-nums ${pnlTone}`}>{fmtPct(dayRate)}</div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:mt-auto sm:pt-3">
        <Mini label="Market Value" value={s.total_value} hidden={hidden} />
        <Mini label="Cash" value={s.total_cash} hidden={hidden} tone={s.total_cash < 0 ? 'neg' : 'neutral'} />
      </div>
    </div>
  )
}

function Mini({
  label, value, hidden, tone = 'neutral',
}: {
  label: string; value: number; hidden: boolean; tone?: 'pos' | 'neg' | 'neutral'
}) {
  const toneClass = tone === 'pos' ? 'text-pos' : tone === 'neg' ? 'text-neg' : 'text-text'
  return (
    <div className="rounded-[10px] bg-surface-2/65 px-3 py-2.5">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-faint">{label}</div>
      <div className={`mt-1 text-[14px] font-semibold leading-none tabular-nums sm:text-[15px] ${toneClass} ${hidden ? 'masked' : ''}`}>
        {fmtUSD(value, hidden)}
      </div>
    </div>
  )
}
