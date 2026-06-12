import { useCallback, useEffect, useState } from 'react'
import { api } from './lib/api'
import type { Status } from './lib/types'
import { useDashboard } from './hooks/useDashboard'
import { Header } from './components/Header'
import { KpiCards } from './components/KpiCards'
import { AllocationCard } from './components/AllocationCard'
import { RebalanceCard } from './components/RebalanceCard'
import { Skeleton } from './components/Skeleton'

export default function App() {
  const {
    account,
    setAccount,
    portfolio,
    accounts,
    targets,
    loading,
    error,
    reload,
    saveTargets,
  } = useDashboard()

  const [hidden, setHidden] = useState(false)
  const [status, setStatus] = useState<Status | null>(null)

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api.status())
    } catch {
      /* non-critical */
    }
  }, [])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  const onRefreshed = useCallback(() => {
    reload()
    loadStatus()
  }, [reload, loadStatus])

  return (
    <div className="min-h-screen">
      <Header
        accounts={accounts}
        account={account}
        onAccount={setAccount}
        hidden={hidden}
        onToggleHidden={() => setHidden((h) => !h)}
        lastRefresh={status?.last_refresh ?? ''}
        mode={status?.mode ?? 'mock'}
        initialCooldown={status?.refresh_cooldown_remaining ?? 0}
        onRefreshed={onRefreshed}
      />

      <main className="mx-auto max-w-7xl px-4 py-5 sm:px-6 sm:py-7">
        {error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : loading && !portfolio ? (
          <Skeleton />
        ) : portfolio ? (
          <div className="space-y-4 sm:space-y-5">
            <KpiCards portfolio={portfolio} hidden={hidden} />
            <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2 sm:gap-5">
              <AllocationCard portfolio={portfolio} hidden={hidden} />
              <RebalanceCard
                portfolio={portfolio}
                savedTargets={targets}
                onSave={saveTargets}
                hidden={hidden}
              />
            </div>
          </div>
        ) : (
          <Skeleton />
        )}
      </main>
    </div>
  )
}

function ErrorState({
  message,
  onRetry,
}: {
  message: string
  onRetry: () => void
}) {
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
