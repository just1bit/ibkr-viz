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
  const [feedback, setFeedback] = useState<{
    kind: 'success' | 'error' | 'info'
    text: string
  } | null>(null)
  const timer = useRef<number | null>(null)
  const feedbackTimer = useRef<number | null>(null)

  useEffect(() => {
    if (initialCooldown > 0) startCooldown(initialCooldown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialCooldown])

  useEffect(() => () => {
    if (timer.current) clearInterval(timer.current)
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current)
  }, [])

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

  function showFeedback(
    kind: 'success' | 'error' | 'info',
    text: string,
    dismissAfterMs?: number,
  ) {
    if (feedbackTimer.current) {
      clearTimeout(feedbackTimer.current)
      feedbackTimer.current = null
    }
    setFeedback({ kind, text })
    if (dismissAfterMs) {
      feedbackTimer.current = window.setTimeout(() => {
        setFeedback(null)
        feedbackTimer.current = null
      }, dismissAfterMs)
    }
  }

  function dismissFeedback() {
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current)
    feedbackTimer.current = null
    setFeedback(null)
  }

  async function refresh() {
    setBusy(true)
    showFeedback('info', 'Starting portfolio refresh…')
    try {
      const r = await api.triggerRefresh((message) => {
        showFeedback('info', message)
      })
      if (r.rateLimited) {
        startCooldown(r.retryAfter)
        showFeedback('info', r.message, 5_000)
      } else if (r.failed) {
        if (r.retryAfter > 0) startCooldown(r.retryAfter)
        showFeedback('error', r.message, 10_000)
      } else {
        onRefreshed()
        startCooldown(600)
        showFeedback('success', r.message, 5_000)
      }
    } catch (err) {
      const message = (err as Error).message
      if (message.includes('still processing after 120 seconds')) {
        startCooldown(600)
      }
      showFeedback('error', message, 10_000)
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
      <div className="mx-auto flex min-h-14 w-full max-w-7xl flex-nowrap items-center gap-2 px-3 py-2 sm:h-16 sm:min-h-16 sm:gap-3 sm:px-6 sm:py-0">
        <div className="flex shrink-0 items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-[12px] bg-accent/12 text-accent sm:h-8 sm:w-8 sm:rounded-[10px]">
            <span className="h-3 w-3 rounded-full bg-accent sm:h-2.5 sm:w-2.5" />
          </div>
          <div className="hidden leading-tight sm:block">
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

        <div className="ml-auto flex min-w-0 flex-1 items-center justify-end gap-1.5 sm:w-auto sm:flex-none sm:gap-2">
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
            className="flex h-10 w-10 shrink-0 items-center justify-center gap-1.5 rounded-[10px] border border-border bg-surface px-2.5 text-[13px] font-medium text-text transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50 min-[375px]:h-9 min-[375px]:w-9 sm:w-auto sm:justify-start sm:px-3"
          >
            <RefreshIcon className={`h-4 w-4 ${busy ? 'animate-spin-slow' : ''}`} />
            <span className="hidden sm:inline tabular-nums">
              {cooldown > 0 ? cooldownLabel : 'Refresh'}
            </span>
          </button>

          <IconButton className="hidden min-[375px]:flex" onClick={onToggleHidden} title={hidden ? 'Show amounts' : 'Hide amounts'}>
            {hidden ? <EyeOffIcon /> : <EyeIcon />}
          </IconButton>

          <IconButton className="hidden min-[375px]:flex" onClick={toggle} title="Toggle theme">
            {isDark ? <SunIcon /> : <MoonIcon />}
          </IconButton>

          <UserMenu
            user={user}
            onLogout={onLogout}
            onSettings={onSettings}
            hidden={hidden}
            onToggleHidden={onToggleHidden}
            isDark={isDark}
            onToggleTheme={toggle}
          />
        </div>
      </div>
      {feedback && (
        <div
          role="status"
          aria-live="polite"
          className={`relative border-t border-border px-10 py-2 text-center text-[12px] ${
            feedback.kind === 'error'
              ? 'bg-neg/10 text-neg'
              : feedback.kind === 'success'
                ? 'bg-pos/10 text-pos'
                : 'bg-accent/10 text-accent'
          }`}
        >
          {feedback.text}
          <button
            type="button"
            onClick={dismissFeedback}
            aria-label="Dismiss notification"
            className="absolute right-4 top-1/2 -translate-y-1/2 rounded px-1.5 py-0.5 text-[16px] leading-none opacity-60 transition-opacity hover:opacity-100"
          >
            ×
          </button>
        </div>
      )}
    </header>
  )
}

function IconButton({
  children,
  onClick,
  title,
  className = '',
}: {
  children: React.ReactNode
  onClick: () => void
  title: string
  className?: string
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border border-border bg-surface text-muted transition-colors hover:bg-surface-2 hover:text-text ${className}`}
    >
      {children}
    </button>
  )
}
