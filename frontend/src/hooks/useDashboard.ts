import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { Account, Portfolio, Targets } from '../lib/types'

interface DashboardData {
  portfolio: Portfolio | null
  accounts: Account[]
  targets: Targets
}

export function useDashboard() {
  const [account, setAccount] = useState('ALL')
  const [data, setData] = useState<DashboardData>({
    portfolio: null,
    accounts: [],
    targets: {},
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const load = useCallback(async (accountId: string) => {
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    const { signal } = ac
    setLoading(true)
    setError(null)
    try {
      const [portfolio, accounts, targets] = await Promise.all([
        api.portfolio(accountId, signal),
        api.accounts(signal),
        api.targets(accountId, signal),
      ])
      setData({ portfolio, accounts, targets })
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      setError((err as Error).message)
    } finally {
      if (!signal.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(account)
  }, [account, load])

  const reload = useCallback(() => load(account), [account, load])

  const saveTargets = useCallback(
    async (targets: Targets) => {
      const saved = await api.saveTargets(account, targets)
      setData((d) => ({ ...d, targets: saved }))
    },
    [account],
  )

  return {
    account,
    setAccount,
    ...data,
    loading,
    error,
    reload,
    saveTargets,
  }
}
