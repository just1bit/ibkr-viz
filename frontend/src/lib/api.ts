import type { Account, Portfolio, Status, Targets } from './types'

export type RefreshResult =
  | { rateLimited: true; retryAfter: number; message: string }
  | { rateLimited: false; failed: true; retryAfter: number; message: string }
  | { rateLimited: false; failed: false; date: string | null; message: string }

async function getJSON<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal, cache: 'no-store' })
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
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId, targets }),
    })
    if (!res.ok) throw new Error('Failed to save targets')
    return (await res.json()).targets as Targets
  },

  status: (signal?: AbortSignal) => getJSON<Status>('/api/status', signal),

  triggerRefresh: async (): Promise<RefreshResult> => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 75_000)
    try {
      const res = await fetch('/api/trigger-refresh', {
        method: 'POST',
        cache: 'no-store',
        signal: controller.signal,
      })
      const data = await res.json()
      if (res.status === 429) {
        return {
          rateLimited: true,
          retryAfter: data.retry_after_seconds as number,
          message: data.message || 'Refresh is temporarily rate limited.',
        }
      }
      if (!res.ok) {
        return {
          rateLimited: false,
          failed: true,
          retryAfter: Number(data.retry_after_seconds || 0),
          message: data.error || 'Refresh failed',
        }
      }
      return {
        rateLimited: false,
        failed: false,
        date: data.date ?? null,
        message: data.message || 'Refresh completed.',
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        throw new Error('Refresh timed out. The server may still be processing the report.')
      }
      throw err
    } finally {
      window.clearTimeout(timeout)
    }
  },
}
