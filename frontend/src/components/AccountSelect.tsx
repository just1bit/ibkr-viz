import { useEffect, useRef, useState } from 'react'
import type { Account } from '../lib/types'
import { fmtUSD } from '../lib/format'

interface Props {
  accounts: Account[]
  value: string
  onChange: (id: string) => void
  hidden: boolean
}

export function AccountSelect({ accounts, value, onChange, hidden }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function click(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', click)
    return () => document.removeEventListener('mousedown', click)
  }, [])

  const current = accounts.find((a) => a.account_id === value)
  const label = value === 'ALL' ? 'All accounts' : (current?.alias || current?.account_id || value)

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex h-11 items-center gap-2 rounded-[10px] border border-border bg-surface px-3 text-[13px] font-medium text-text transition-colors hover:bg-surface-2 sm:h-9"
      >
        <span className="max-w-[140px] truncate">{label}</span>
        <svg className="h-3 w-3 text-faint" viewBox="0 0 12 12" fill="none">
          <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-[calc(100vw-3rem)] max-w-[280px] rounded-[12px] border border-border bg-surface p-1 shadow-lg">
          <button
            onClick={() => { onChange('ALL'); setOpen(false) }}
            className={`flex min-h-11 w-full items-center justify-between rounded-[9px] px-3 py-2 text-left ${
              value === 'ALL' ? 'bg-surface-2' : 'hover:bg-surface-2'
            }`}
          >
            <span className="text-[13px] font-medium text-text">All accounts</span>
          </button>
          {accounts.map((a) => (
            <button
              key={a.account_id}
              onClick={() => { onChange(a.account_id); setOpen(false) }}
              className={`flex min-h-11 w-full items-center justify-between rounded-[9px] px-3 py-2 text-left ${
                value === a.account_id ? 'bg-surface-2' : 'hover:bg-surface-2'
              }`}
            >
              <div>
                <div className="text-[13px] font-medium text-text">{a.alias || a.account_id}</div>
                <div className="text-[10px] text-faint">{a.account_id} · {a.account_type}</div>
              </div>
              <span className={`tabular-nums text-[12px] text-muted ${hidden ? 'masked' : ''}`}>
                {fmtUSD(a.net_liquidation, hidden)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
