import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { UserProfile, FlexTestResult, ConfigureResult } from '../lib/types'

type AuthState =
  | { status: 'loading' }
  | { status: 'authenticated'; user: UserProfile }
  | { status: 'unauthenticated' }

interface AuthContextValue {
  authState: AuthState
  user: UserProfile | null
  loading: boolean
  login: () => void
  logout: () => Promise<void>
  testFlex: (token: string, queryId: string) => Promise<FlexTestResult>
  configureFlex: (token: string, queryId: string) => Promise<ConfigureResult>
}

const AuthCtx = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authState, setAuthState] = useState<AuthState>({ status: 'loading' })

  const fetchUser = useCallback(async () => {
    try {
      const res = await fetch('/auth/me')
      if (!res.ok) { setAuthState({ status: 'unauthenticated' }); return }
      setAuthState({ status: 'authenticated', user: await res.json() })
    } catch {
      setAuthState({ status: 'unauthenticated' })
    }
  }, [])

  useEffect(() => { fetchUser() }, [fetchUser])

  const login = useCallback(() => { window.location.href = '/auth/login' }, [])

  const logout = useCallback(async () => {
    await fetch('/auth/logout', { method: 'POST' })
    setAuthState({ status: 'unauthenticated' })
  }, [])

  const testFlex = useCallback(async (token: string, queryId: string): Promise<FlexTestResult> => {
    const res = await fetch('/api/setup/test-flex', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, query_id: queryId }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || 'Test failed')
    return data as FlexTestResult
  }, [])

  const configureFlex = useCallback(async (token: string, queryId: string): Promise<ConfigureResult> => {
    const res = await fetch('/api/setup/configure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, query_id: queryId }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || 'Configuration failed')
    if (!data.fetch_error) {
      await fetchUser()
    }
    return data as ConfigureResult
  }, [fetchUser])

  return (
    <AuthCtx.Provider value={{
      authState, user: authState.status === 'authenticated' ? authState.user : null,
      loading: authState.status === 'loading', login, logout, testFlex, configureFlex,
    }}>
      {children}
    </AuthCtx.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthCtx)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
