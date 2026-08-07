import type { Portfolio } from '../lib/types'
import { fmtPct, fmtUSD } from '../lib/format'

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

  return (
    <div className="flex h-full min-h-[246px] flex-col rounded-[var(--radius-lg)] border border-border bg-surface p-5 shadow-[var(--shadow)] sm:min-h-0">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-[14px] font-semibold tracking-tight text-text sm:text-[13px]">Portfolio</h2>
        <span className="text-[12px] text-faint tabular-nums sm:text-[11px]">{portfolio.date}</span>
      </div>

      <div className="mt-4 sm:mt-3">
        <p
          className={`text-[32px] font-bold leading-none tracking-tight tabular-nums text-text sm:text-[34px] ${
            hidden ? 'masked' : ''
          }`}
        >
          {fmtUSD(nav, hidden)}
        </p>

        <div className="mt-5 sm:mt-4">
          <p
            className={`text-[30px] font-bold leading-none tabular-nums sm:text-[34px] ${pnlTone}`}
          >
            {fmtPct(dayRate)}
          </p>
          <div className="mt-1.5 flex items-baseline gap-1.5">
            <span className={`text-[14px] font-semibold tabular-nums ${pnlTone} ${hidden ? 'masked' : ''}`}>
              {s.total_day_pnl >= 0 ? '+' : ''}{fmtUSD(s.total_day_pnl, hidden)}
            </span>
            <span className="text-[11px] text-faint">Today</span>
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 border-t border-border pt-4 sm:mt-auto sm:gap-2 sm:pt-4">
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
    <div>
      <div className="text-[11px] font-medium uppercase tracking-wide text-faint sm:text-[10px]">{label}</div>
      <div className={`mt-0.5 text-[14px] font-semibold leading-none tabular-nums sm:text-[15px] ${toneClass} ${hidden ? 'masked' : ''}`}>
        {fmtUSD(value, hidden)}
      </div>
    </div>
  )
}
