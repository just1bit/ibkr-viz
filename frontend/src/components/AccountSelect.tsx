import { useEffect, useRef, useState } from 'react'
import type { Account } from '../lib/types'
import { fmtUSD } from '../lib/format'
import { CheckIcon, ChevronIcon } from './icons'

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
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const selected = accounts.find((a) => a.account_id === value)
  const label =
    value === 'ALL' ? 'All accounts' : selected?.alias || value

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex h-9 items-center gap-2 rounded-[10px] border border-border bg-surface px-3 text-[13px] font-medium text-text transition-colors hover:bg-surface-2"
      >
        <span className="tnum">{label}</span>
        <ChevronIcon
          className={`h-3.5 w-3.5 text-faint transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-60 origin-top-right overflow-hidden rounded-[12px] border border-border bg-surface p-1 shadow-[var(--shadow)] animate-fade-up">
          <Row
            label="All accounts"
            sub={`${accounts.length} accounts`}
            active={value === 'ALL'}
            onClick={() => {
              onChange('ALL')
              setOpen(false)
            }}
          />
          <div className="my-1 h-px bg-border" />
          {accounts.map((a) => (
            <Row
              key={a.account_id}
              label={a.alias || a.account_id}
              meta={a.alias ? a.account_id : undefined}
              sub={fmtUSD(a.net_liquidation, hidden)}
              tag={a.account_type}
              active={value === a.account_id}
              onClick={() => {
                onChange(a.account_id)
                setOpen(false)
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function Row({
  label,
  meta,
  sub,
  tag,
  active,
  onClick,
}: {
  label: string
  meta?: string
  sub: string
  tag?: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-[8px] px-3 py-2 text-left transition-colors ${
        active ? 'bg-surface-2' : 'hover:bg-surface-2'
      }`}
    >
      <span className="flex h-4 w-4 shrink-0 items-center justify-center text-accent">
        {active && <CheckIcon className="h-4 w-4" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-text">{label}</span>
        {meta && <span className="block tnum text-[10px] text-faint">{meta}</span>}
      </span>
      {tag && (
        <span className="rounded-full border border-border px-1.5 py-0.5 text-[9px] font-semibold tracking-wide text-faint">
          {tag}
        </span>
      )}
      <span className="tnum text-[12px] text-muted">{sub}</span>
    </button>
  )
}
