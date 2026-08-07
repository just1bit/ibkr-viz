import { useEffect, useState } from 'react'
import { useAuth } from '../hooks/useAuth'

type Step = 'input' | 'testing' | 'test_done' | 'saving' | 'saved'

interface Props {
  mode?: 'setup' | 'settings'
  onDone?: () => void
}

export function SetupPage({ mode = 'setup', onDone }: Props) {
  const { user, testFlex, configureFlex } = useAuth()
  const [token, setToken] = useState('')
  const [queryId, setQueryId] = useState(user?.flex_query_id ?? '')
  const [showToken, setShowToken] = useState(false)
  const [step, setStep] = useState<Step>('input')
  const [testResult, setTestResult] = useState<{
    accounts: Array<{ account_id: string; alias: string; account_type: string }>
    report_date: string
  } | null>(null)
  const [error, setError] = useState('')
  const [configureError, setConfigureError] = useState('')

  useEffect(() => {
    if (!onDone) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onDone()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onDone])

  async function handleTest() {
    if (!token.trim() || !queryId.trim()) {
      setError('Both Token and Query ID are required.')
      return
    }
    setError('')
    setStep('testing')
    try {
      const result = await testFlex(token.trim(), queryId.trim())
      setTestResult({ accounts: result.accounts, report_date: result.report_date })
      setStep('test_done')
    } catch (err) {
      setError((err as Error).message)
      setStep('input')
    }
  }

  async function handleSave() {
    setConfigureError('')
    setStep('saving')
    try {
      const result = await configureFlex(token.trim(), queryId.trim())
      if (result.fetch_error) {
        setConfigureError(result.fetch_error)
        setStep('test_done')
        return
      }
      setStep('saved')
      setTimeout(() => onDone?.(), 600)
    } catch (err) {
      setConfigureError((err as Error).message)
      setStep('test_done')
    }
  }

  return (
    <div className="min-h-screen px-4 py-5 sm:flex sm:items-center sm:justify-center sm:px-6 sm:py-12">
      <div className="mx-auto w-full max-w-md">
        {onDone && (
          <button
            type="button"
            onClick={onDone}
            className="mb-8 inline-flex min-h-11 items-center gap-2 rounded-[10px] px-1 text-[14px] font-medium text-muted transition-colors hover:text-text sm:mb-7 sm:min-h-0 sm:text-[13px]"
          >
            <span aria-hidden="true" className="text-[18px] leading-none">←</span>
            Back to dashboard
          </button>
        )}
        <h1 className="text-[22px] font-semibold tracking-tight text-text">
          {mode === 'settings'
            ? 'IBKR settings'
            : `Welcome${user?.name ? `, ${user.name.split(' ')[0]}` : ''}`}
        </h1>
        <p className="mt-2 text-[14px] leading-relaxed text-muted">
          {mode === 'settings'
            ? 'Update the Flex Query used to keep your portfolio data in sync.'
            : 'Connect your Interactive Brokers account to get started.'}
        </p>

        <div className="mt-7 space-y-4">
          {user?.flex_token_masked && (
            <div className="rounded-[10px] border border-border bg-surface-2/60 px-3 py-2.5">
              <div className="text-[12px] text-muted">Saved Flex token</div>
              <code className="mt-1 block font-mono text-[13px] tracking-wide text-text">
                {user.flex_token_masked}
              </code>
              <div className="mt-1 text-[11px] text-faint">
                The full token remains encrypted. Enter a new token below only to replace it.
              </div>
            </div>
          )}

          <div>
            <label className="mb-1.5 block text-[13px] font-medium text-text">
              {user?.flex_token_masked ? 'New Flex Web Service Token' : 'Flex Web Service Token'}
            </label>
            <div className="relative">
              <input
                type={showToken ? 'text' : 'password'}
                value={token}
                onChange={(e) => { setToken(e.target.value); setError('') }}
                placeholder={user?.flex_token_masked
                  ? 'Paste a new token to replace the saved token'
                  : 'Paste your IBKR Flex token'}
                className="h-11 w-full rounded-[10px] border border-border bg-surface px-3 pr-16 text-[16px] text-text placeholder:text-faint focus:border-accent focus:outline-none sm:h-10 sm:text-[13px]"
              />
              <button
                type="button"
                onClick={() => setShowToken((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[12px] text-muted hover:text-text"
              >
                {showToken ? 'Hide' : 'Show'}
              </button>
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-[13px] font-medium text-text">
              Flex Query ID
            </label>
            <input
              type="text"
              value={queryId}
              onChange={(e) => { setQueryId(e.target.value); setError('') }}
              placeholder="e.g. 1510531"
              className="h-11 w-full rounded-[10px] border border-border bg-surface px-3 text-[16px] text-text placeholder:text-faint focus:border-accent focus:outline-none sm:h-10 sm:text-[13px]"
            />
          </div>

          <div className="flex gap-3 max-[359px]:flex-col">
            <button
              onClick={handleTest}
              disabled={step === 'testing' || step === 'saving'}
              className="flex h-11 items-center gap-2 rounded-[10px] border border-border bg-surface px-4 text-[13px] font-medium text-text transition-colors hover:bg-surface-2 disabled:opacity-50 max-[359px]:w-full max-[359px]:justify-center sm:h-10"
            >
              {step === 'testing' ? (
                <>
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-muted border-t-accent" />
                  Testing...
                </>
              ) : (
                'Test Connection'
              )}
            </button>

            <button
              onClick={handleSave}
              disabled={step !== 'test_done'}
              className="flex h-11 items-center gap-2 rounded-[10px] bg-accent px-4 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50 max-[359px]:w-full max-[359px]:justify-center sm:h-10"
            >
              {step === 'saving' ? (
                <>
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  Saving...
                </>
              ) : (
                'Save & Go to Dashboard'
              )}
            </button>
          </div>

          {error && (
            <div className="rounded-[10px] border border-neg/30 bg-neg/6 px-3 py-2.5 text-[13px] text-neg">
              {error}
            </div>
          )}
          {configureError && (
            <div className="rounded-[10px] border border-neg/30 bg-neg/6 px-3 py-2.5 text-[13px] text-neg">
              {configureError}
            </div>
          )}

          {testResult && step !== 'input' && (
            <div className="rounded-[12px] border border-pos/30 bg-pos/5 p-4">
              <p className="text-[13px] font-medium text-pos">
                ✓ Connected! Report date: {testResult.report_date}
              </p>
              <p className="mt-1 text-[12px] text-muted">Accounts found:</p>
              <ul className="mt-1 space-y-0.5">
                {testResult.accounts.map((a) => (
                  <li key={a.account_id} className="text-[13px] text-text">
                    &bull; {a.alias || a.account_id}{' '}
                    <span className="text-faint">({a.account_id}) — {a.account_type}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <p className="mt-6 text-[12px] text-faint">
          Find your token and query ID in IBKR Client Portal → Performance &amp; Reports
          → Flex Queries. Your token is stored encrypted.
        </p>
      </div>
    </div>
  )
}
