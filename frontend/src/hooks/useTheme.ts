import { useCallback, useEffect, useSyncExternalStore } from 'react'

type Theme = 'light' | 'dark'

function current(): Theme {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
}

const listeners = new Set<() => void>()
function subscribe(cb: () => void) {
  listeners.add(cb)
  return () => listeners.delete(cb)
}
function emit() {
  listeners.forEach((l) => l())
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, current, () => 'dark' as Theme)

  const toggle = useCallback(() => {
    const next: Theme = current() === 'dark' ? 'light' : 'dark'
    document.documentElement.classList.toggle('dark', next === 'dark')
    document.documentElement.style.colorScheme = next
    try {
      localStorage.setItem('theme', next)
    } catch {
      /* ignore */
    }
    emit()
  }, [])

  // Keep in sync with OS preference until the user makes an explicit choice.
  useEffect(() => {
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => {
      if (localStorage.getItem('theme')) return
      document.documentElement.classList.toggle('dark', e.matches)
      emit()
    }
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  return { theme, toggle, isDark: theme === 'dark' }
}
