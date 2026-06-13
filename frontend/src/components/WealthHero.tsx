import type { Portfolio } from '../lib/types'
import { fmtPct, fmtUSD } from '../lib/format'

interface Props {
  portfolio: Portfolio
  hidden: boolean
}

export function WealthHero({ portfolio, hidden }: Props) {
  const s = portfolio.summary
  const nav = s.net_liquidation
  const dayRate = nav ? (s.total_day_pnl / (nav - s.total_day_pnl)) * 100 : 0
  const pnlTone = s.total_day_pnl >= 0 ? 'text-pos' : 'text-neg'

  return (
    <div className="flex h-full flex-col justify-between rounded-[var(--radius-lg)] border border-border bg-surface p-4 shadow-[var(--shadow)] sm:p-5">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-[13px] font-semibold tracking-tight text-text">Portfolio</h2>
        <span className="text-[11px] text-faint tabular-nums">{portfolio.date}</span>
      </div>

      <p
        className={`mt-2 text-[30px] font-bold leading-none tracking-tight tabular-nums text-text sm:text-[34px] ${
          hidden ? 'masked' : ''
        }`}
      >
        {fmtUSD(nav, hidden)}
      </p>

      <div className="mt-2">
        <p
          className={`text-[30px] font-bold leading-none tabular-nums sm:text-[34px] ${pnlTone}`}
        >
          {fmtPct(dayRate)}
        </p>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span className={`text-[14px] font-semibold tabular-nums ${pnlTone} ${hidden ? 'masked' : ''}`}>
            {s.total_day_pnl >= 0 ? '+' : ''}{fmtUSD(s.total_day_pnl, hidden)}
          </span>
          <span className="text-[11px] text-faint">Today</span>
        </div>
      </div>

      <div className="mt-auto grid grid-cols-2 gap-2 border-t border-border pt-3">
        <Mini label="Invested" value={s.total_value} hidden={hidden} />
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
    <div>
      <div className="text-[10px] font-medium uppercase tracking-wide text-faint">{label}</div>
      <div className={`mt-0.5 text-[14px] font-semibold leading-none tabular-nums sm:text-[15px] ${toneClass} ${hidden ? 'masked' : ''}`}>
        {fmtUSD(value, hidden)}
      </div>
    </div>
  )
}
