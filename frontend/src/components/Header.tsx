import { useEffect, useRef, useState } from 'react'
import type { Account, UserProfile } from '../lib/types'
import { api } from '../lib/api'
import { useTheme } from '../hooks/useTheme'
import { AccountSelect } from './AccountSelect'
import { UserMenu } from './UserMenu'
import { EyeIcon, EyeOffIcon, MoonIcon, RefreshIcon, SunIcon } from './icons'

interface Props {
  accounts: Account[]
  account: string
  onAccount: (id: string) => void
  hidden: boolean
  onToggleHidden: () => void
  lastRefresh: string
  initialCooldown: number
  onRefreshed: () => void
  user: UserProfile
  onLogout: () => void
  onSettings?: () => void
}

export function Header({
  accounts,
  account,
  onAccount,
  hidden,
  onToggleHidden,
  lastRefresh,
  initialCooldown,
  onRefreshed,
  user,
  onLogout,
  onSettings,
}: Props) {
  const { isDark, toggle } = useTheme()
  const [cooldown, setCooldown] = useState(0)
  const [busy, setBusy] = useState(false)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    if (initialCooldown > 0) startCooldown(initialCooldown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialCooldown])

  function startCooldown(seconds: number) {
    if (timer.current) clearInterval(timer.current)
    setCooldown(seconds)
    timer.current = window.setInterval(() => {
      setCooldown((c) => {
        if (c <= 1) {
          if (timer.current) clearInterval(timer.current)
          return 0
        }
        return c - 1
      })
    }, 1000)
  }

  async function refresh() {
    setBusy(true)
    try {
      const r = await api.triggerRefresh()
      if (r.rateLimited) {
        startCooldown(r.retryAfter)
      } else {
        onRefreshed()
        startCooldown(600)
      }
    } catch {
      /* surfaced elsewhere */
    } finally {
      setBusy(false)
    }
  }

  const cooldownLabel = (() => {
    if (cooldown <= 0) return ''
    const m = Math.floor(cooldown / 60)
    const s = cooldown % 60
    return m > 0 ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`
  })()

  return (
    <header className="safe-top sticky top-0 z-40 border-b border-border bg-bg/80 backdrop-blur-xl">
      <div className="mx-auto flex min-h-16 w-full max-w-7xl flex-wrap items-center gap-3 px-4 py-3 sm:h-16 sm:flex-nowrap sm:px-6 sm:py-0">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-accent/12 text-accent">
            <span className="h-2.5 w-2.5 rounded-full bg-accent" />
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-tight text-text">
              Portfolio
            </div>
            <div className="hidden text-[11px] text-faint sm:block">
              IBKR Flex
              {lastRefresh && lastRefresh !== 'Never' && (
                <span className="tabular-nums"> · {lastRefresh}</span>
              )}
            </div>
          </div>
        </div>

        <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:ml-auto sm:w-auto sm:flex-nowrap">
          <AccountSelect
            accounts={accounts}
            value={account}
            onChange={onAccount}
            hidden={hidden}
          />

          <button
            onClick={refresh}
            disabled={busy || cooldown > 0}
            title="Refresh data"
            className="flex h-11 w-11 items-center justify-center gap-1.5 rounded-[10px] border border-border bg-surface px-3 text-[13px] font-medium text-text transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50 sm:h-9 sm:w-auto sm:justify-start"
          >
            <RefreshIcon className={`h-4 w-4 ${busy ? 'animate-spin-slow' : ''}`} />
            <span className="hidden sm:inline tabular-nums">
              {cooldown > 0 ? cooldownLabel : 'Refresh'}
            </span>
          </button>

          <IconButton onClick={onToggleHidden} title={hidden ? 'Show amounts' : 'Hide amounts'}>
            {hidden ? <EyeOffIcon /> : <EyeIcon />}
          </IconButton>

          <IconButton onClick={toggle} title="Toggle theme">
            {isDark ? <SunIcon /> : <MoonIcon />}
          </IconButton>

          <UserMenu user={user} onLogout={onLogout} onSettings={onSettings} />
        </div>
      </div>
    </header>
  )
}

function IconButton({
  children,
  onClick,
  title,
}: {
  children: React.ReactNode
  onClick: () => void
  title: string
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="flex h-11 w-11 items-center justify-center rounded-[10px] border border-border bg-surface text-muted transition-colors hover:bg-surface-2 hover:text-text sm:h-9 sm:w-9"
    >
      {children}
    </button>
  )
}
