import type { Account, Portfolio, Status, Targets } from './types'

export type RefreshResult =
  | { rateLimited: true; retryAfter: number; message: string }
  | { rateLimited: false; failed: true; retryAfter: number; message: string }
  | { rateLimited: false; failed: false; date: string | null; message: string }

type RefreshJobStatus = {
  status: 'running' | 'success' | 'error'
  date?: string | null
  message: string
  retry_after_seconds?: number
}

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

  triggerRefresh: async (
    onProgress?: (message: string) => void,
  ): Promise<RefreshResult> => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 120_000)
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

      const jobId = Number(data.job_id)
      if (!Number.isFinite(jobId)) {
        throw new Error('Refresh started without a valid job id.')
      }
      onProgress?.(data.message || 'Refresh started')

      while (true) {
        await wait(1_000)
        const statusRes = await fetch(`/api/refresh-status/${jobId}`, {
          cache: 'no-store',
          signal: controller.signal,
        })
        const job = await statusRes.json() as RefreshJobStatus & { error?: string }
        if (!statusRes.ok) {
          throw new Error(job.error || `Refresh status failed (${statusRes.status})`)
        }
        if (job.status === 'running') {
          onProgress?.(job.message || 'Refresh is running')
          continue
        }
        if (job.status === 'error') {
          return {
            rateLimited: false,
            failed: true,
            retryAfter: Number(job.retry_after_seconds || 0),
            message: job.message || 'Refresh failed',
          }
        }
        return {
          rateLimited: false,
          failed: false,
          date: job.date ?? null,
          message: job.message || 'Refresh completed.',
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        throw new Error(
          'Refresh is still processing after 120 seconds. The server will continue in the background.',
        )
      }
      throw err
    } finally {
      window.clearTimeout(timeout)
    }
  },
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}
