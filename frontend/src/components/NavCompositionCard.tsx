import type { Account, Portfolio } from '../lib/types'
import { fmtUSD, fmtUSDFull } from '../lib/format'

interface Props {
  portfolio: Portfolio
  accounts: Account[]
  hidden: boolean
}

const SEGMENT_COLORS: Record<string, string> = {
  Stocks: 'bg-accent/80',
  Options: 'bg-[#a78bfa]',
  Cash: 'bg-[#8b8b94]',
  Accruals: 'bg-[#f0a868]',
}

/**
 * NAV decomposition straight from EquitySummaryInBase: stocks, options, cash
 * and accruals, plus the per-account split (with profile badges) in the
 * merged view. Negative cash (margin debit) renders as a red row and is
 * excluded from the proportion bar.
 */
export function NavCompositionCard({ portfolio, accounts, hidden }: Props) {
  const e = portfolio.equity
  const rows = [
    { label: 'Stocks', value: e.stock },
    { label: 'Options', value: e.options },
    { label: 'Cash', value: e.cash },
    { label: 'Dividend accruals', value: e.dividend_accruals },
    { label: 'Interest accruals', value: e.interest_accruals },
  ].filter((r) => r.value !== 0)

  const positives = rows.filter((r) => r.value > 0)
  const posTotal = positives.reduce((s, r) => s + r.value, 0)
  const showAccounts = portfolio.account_id === 'ALL' && accounts.length > 1

  return (
    <div className="rounded-[var(--radius-lg)] border border-border bg-surface p-5 shadow-[var(--shadow)] sm:p-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[15px] font-semibold tracking-tight text-text">
          NAV composition
        </h2>
        <span className={`tnum text-[12px] font-semibold text-text ${hidden ? 'masked' : ''}`}>
          {fmtUSD(e.total, hidden)}
        </span>
      </div>

      {posTotal > 0 && (
        <div className="mt-4 flex h-2 w-full gap-0.5 overflow-hidden rounded-full">
          {positives.map((r) => (
            <div
              key={r.label}
              title={r.label}
              className={`${barColor(r.label)} h-full rounded-full`}
              style={{ width: `${(r.value / posTotal) * 100}%` }}
            />
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-col">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center gap-2.5 py-1.5">
            <span className={`h-2 w-2 shrink-0 rounded-[3px] ${barColor(r.label)}`} />
            <span className="flex-1 text-[12px] font-medium text-text">{r.label}</span>
            <span
              className={`tnum text-[12px] ${r.value < 0 ? 'text-neg' : 'text-muted'} ${hidden ? 'masked' : ''}`}
            >
              {fmtUSDFull(r.value, hidden)}
            </span>
            <span className="w-12 text-right tnum text-[11px] text-faint">
              {e.total !== 0 ? ((r.value / e.total) * 100).toFixed(1) : '0.0'}%
            </span>
          </div>
        ))}
      </div>

      {showAccounts && (
        <>
          <div className="mt-3 border-t border-border pt-3 text-[10px] font-medium uppercase tracking-wide text-faint">
            By account
          </div>
          <div className="mt-1 flex flex-col">
            {accounts.map((a) => (
              <div key={a.account_id} className="flex items-center gap-2 py-1.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-[12px] font-medium text-text">
                      {a.alias || a.account_id}
                    </span>
                    <Badge>{a.account_type}</Badge>
                    {a.syep === 'enabled' && <Badge>SYEP</Badge>}
                    {a.drip === 'Yes' && <Badge>DRIP</Badge>}
                  </div>
                  <div className="tnum text-[10px] text-faint">
                    {a.account_id}
                    {a.date_opened && ` · since ${a.date_opened}`}
                  </div>
                </div>
                <span className={`tnum text-[12px] text-muted ${hidden ? 'masked' : ''}`}>
                  {fmtUSD(a.net_liquidation, hidden)}
                </span>
                <span
                  className={`w-[72px] text-right tnum text-[11px] font-medium ${
                    a.day_pnl >= 0 ? 'text-pos' : 'text-neg'
                  } ${hidden ? 'masked' : ''}`}
                >
                  {a.day_pnl >= 0 ? '+' : ''}
                  {fmtUSD(a.day_pnl, hidden)}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function barColor(label: string): string {
  if (label.includes('accrual')) return SEGMENT_COLORS.Accruals
  return SEGMENT_COLORS[label] ?? 'bg-faint/40'
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="shrink-0 rounded-full border border-border px-1.5 py-px text-[9px] font-semibold tracking-wide text-faint">
      {children}
    </span>
  )
}
