import type { Account, Portfolio, Status, Targets } from './types'

async function getJSON<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal })
  if (!res.ok) {
    let detail = ''
    try {
      detail = (await res.json()).error ?? ''
    } catch {
      /* ignore */
    }
    throw new Error(detail || `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

export const api = {
  accounts: (signal?: AbortSignal) =>
    getJSON<{ accounts: Account[] }>('/api/accounts', signal).then(
      (r) => r.accounts,
    ),

  portfolio: (accountId: string, signal?: AbortSignal) =>
    getJSON<Portfolio>(
      `/api/portfolio?account_id=${encodeURIComponent(accountId)}`,
      signal,
    ),

  targets: (accountId: string, signal?: AbortSignal) =>
    getJSON<{ account_id: string; targets: Targets }>(
      `/api/targets?account_id=${encodeURIComponent(accountId)}`,
      signal,
    ).then((r) => r.targets),

  saveTargets: async (accountId: string, targets: Targets) => {
    const res = await fetch('/api/targets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId, targets }),
    })
    if (!res.ok) throw new Error('Failed to save targets')
    return (await res.json()).targets as Targets
  },

  status: (signal?: AbortSignal) => getJSON<Status>('/api/status', signal),

  triggerRefresh: async () => {
    const res = await fetch('/api/trigger-refresh')
    const data = await res.json()
    if (res.status === 429) {
      return { rateLimited: true, retryAfter: data.retry_after_seconds as number }
    }
    if (!res.ok) throw new Error(data.error || 'Refresh failed')
    return { rateLimited: false, ...data }
  },
}
