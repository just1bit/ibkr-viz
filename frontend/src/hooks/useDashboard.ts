import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { Account, Portfolio, Targets } from '../lib/types'

export function useDashboard() {
  const [account, setAccount] = useState('ALL')
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [targets, setTargets] = useState<Targets>({})
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
      const [p, a, t] = await Promise.all([
        api.portfolio(accountId, signal),
        api.accounts(signal),
        api.targets(accountId, signal),
      ])
      setPortfolio(p)
      setAccounts(a)
      setTargets(t)
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      setError((err as Error).message)
    } finally {
      if (!signal.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => { load(account) }, [account, load])

  const reload = useCallback(() => load(account), [account, load])

  const saveTargets = useCallback(async (t: Targets) => {
    const saved = await api.saveTargets(account, t)
    setTargets(saved)
  }, [account])

  return { account, setAccount, portfolio, accounts, targets, loading, error, reload, saveTargets }
}
