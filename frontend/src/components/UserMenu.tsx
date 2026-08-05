import { useEffect, useRef, useState } from 'react'
import type { UserProfile } from '../lib/types'

interface Props {
  user: UserProfile
  onLogout: () => void
  onSettings?: () => void
}

export function UserMenu({ user, onLogout, onSettings }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function click(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', click)
    return () => document.removeEventListener('mousedown', click)
  }, [])

  const initial = (user.name || user.email || '?')[0].toUpperCase()

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex h-11 w-11 items-center justify-center rounded-full border border-border bg-surface text-[13px] font-semibold text-text transition-colors hover:bg-surface-2 sm:h-9 sm:w-9"
        title={user.email}
      >
        {initial}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-[220px] rounded-[12px] border border-border bg-surface p-1 shadow-lg">
          <div className="px-3 py-2">
            <div className="truncate text-[13px] font-medium text-text">{user.name || user.email}</div>
            <div className="truncate text-[11px] text-faint">{user.email}</div>
          </div>
          <div className="my-1 border-t border-border" />
          {onSettings && (
            <button
              onClick={() => { onSettings(); setOpen(false) }}
              className="flex min-h-11 w-full items-center rounded-[9px] px-3 py-2 text-left text-[13px] text-text transition-colors hover:bg-surface-2"
            >
              IBKR Settings
            </button>
          )}
          <button
            onClick={() => { onLogout(); setOpen(false) }}
            className="flex min-h-11 w-full items-center rounded-[9px] px-3 py-2 text-left text-[13px] text-text transition-colors hover:bg-surface-2"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
