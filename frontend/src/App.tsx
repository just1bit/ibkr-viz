import { useCallback, useEffect, useState } from 'react'
import { AuthProvider, useAuth } from './hooks/useAuth'
import { api } from './lib/api'
import type { Status } from './lib/types'
import { useDashboard } from './hooks/useDashboard'
import { Header } from './components/Header'
import { WealthHero } from './components/WealthHero'
import { DayPnlCard } from './components/DayPnlCard'
import { HoldingsCard } from './components/HoldingsCard'
import { Skeleton } from './components/Skeleton'
import { LoginPage } from './components/LoginPage'
import { SetupPage } from './components/SetupPage'
import { ConnectionBanner } from './components/ConnectionBanner'

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}

function AppContent() {
  const { authState, user, logout } = useAuth()
  const [showSettings, setShowSettings] = useState(false)

  if (authState.status === 'loading') {
    return <FullPageSkeleton />
  }

  if (authState.status === 'unauthenticated') {
    return <LoginPage />
  }

  // Flex not configured → setup flow
  if (user && (!user.has_flex_query || showSettings)) {
    return <SetupPage onDone={() => setShowSettings(false)} />
  }

  return <Dashboard user={user!} onLogout={logout} onSettings={() => setShowSettings(true)} />
}

function Dashboard({ user, onLogout, onSettings }: {
  user: NonNullable<ReturnType<typeof useAuth>['user']>
  onLogout: () => void
  onSettings: () => void
}) {
  const { account, setAccount, portfolio, accounts, targets, loading, error, reload, saveTargets } = useDashboard()
  const [hidden, setHidden] = useState(false)
  const [status, setStatus] = useState<Status | null>(null)

  const loadStatus = useCallback(async () => {
    try { setStatus(await api.status()) } catch { /* non-critical */ }
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  const onRefreshed = useCallback(() => { reload(); loadStatus() }, [reload, loadStatus])

  return (
    <div className="min-h-screen">
      <Header
        accounts={accounts}
        account={account}
        onAccount={setAccount}
        hidden={hidden}
        onToggleHidden={() => setHidden((h) => !h)}
        lastRefresh={status?.last_refresh ?? ''}
        initialCooldown={status?.refresh_cooldown_remaining ?? 0}
        onRefreshed={onRefreshed}
        user={user}
        onLogout={onLogout}
        onSettings={onSettings}
      />

      <ConnectionBanner user={user} />

      <main className="mx-auto max-w-7xl px-4 py-5 sm:px-6 sm:py-7">
        {error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : loading && !portfolio ? (
          <Skeleton />
        ) : portfolio ? (
          <div className="space-y-4 sm:space-y-5">
            <div className="grid grid-cols-1 items-stretch gap-4 sm:gap-5 lg:grid-cols-12">
              <div className="lg:col-span-4">
                <WealthHero portfolio={portfolio} hidden={hidden} />
              </div>
              <div className="lg:col-span-8">
                <DayPnlCard portfolio={portfolio} hidden={hidden} />
              </div>
            </div>

            <HoldingsCard
              portfolio={portfolio}
              savedTargets={targets}
              onSave={saveTargets}
              hidden={hidden}
            />
          </div>
        ) : (
          <Skeleton />
        )}
      </main>
    </div>
  )
}

function FullPageSkeleton() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <div className="flex h-14 w-14 items-center justify-center rounded-[14px] bg-accent/12">
          <span className="h-4 w-4 animate-pulse rounded-full bg-accent/60" />
        </div>
        <span className="text-[14px] text-muted">Loading...</span>
      </div>
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-[var(--radius-lg)] border border-border bg-surface py-20 text-center">
      <p className="text-[14px] text-neg">{message}</p>
      <button
        onClick={onRetry}
        className="rounded-[10px] bg-accent px-4 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
      >
        Try again
      </button>
    </div>
  )
}
