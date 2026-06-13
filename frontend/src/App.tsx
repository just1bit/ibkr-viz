import { useCallback, useEffect, useState } from 'react'
import { api } from './lib/api'
import type { Status } from './lib/types'
import { useDashboard } from './hooks/useDashboard'
import { Header } from './components/Header'
import { KpiCards } from './components/KpiCards'
import { AllocationCard } from './components/AllocationCard'
import { DayPnlCard } from './components/DayPnlCard'
import { PositionsCard } from './components/PositionsCard'
import { NavCompositionCard } from './components/NavCompositionCard'
import { CashFlowCard } from './components/CashFlowCard'
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

            {/* Today: allocation snapshot + what moved the book */}
            <div className="grid grid-cols-1 items-stretch gap-4 sm:gap-5 lg:grid-cols-12">
              <div className="lg:col-span-5">
                <AllocationCard portfolio={portfolio} hidden={hidden} />
              </div>
              <div className="lg:col-span-7">
                <DayPnlCard portfolio={portfolio} hidden={hidden} />
              </div>
            </div>

            {/* Detail: every statement figure per holding */}
            <PositionsCard portfolio={portfolio} hidden={hidden} />

            {/* Plan & context: rebalance + NAV breakdown + income/costs */}
            <div className="grid grid-cols-1 items-stretch gap-4 sm:gap-5 lg:grid-cols-12">
              <div className="lg:col-span-7">
                <RebalanceCard
                  portfolio={portfolio}
                  savedTargets={targets}
                  onSave={saveTargets}
                  hidden={hidden}
                />
              </div>
              <div className="flex flex-col gap-4 sm:gap-5 lg:col-span-5">
                <NavCompositionCard
                  portfolio={portfolio}
                  accounts={accounts}
                  hidden={hidden}
                />
                <CashFlowCard portfolio={portfolio} hidden={hidden} />
              </div>
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
