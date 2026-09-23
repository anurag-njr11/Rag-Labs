import { useCallback, useState } from 'react'

export type Theme = 'light' | 'dark'

const current = (): Theme => (document.documentElement.classList.contains('dark') ? 'dark' : 'light')

/** Light/dark theme toggled via <html class="dark">; persisted to localStorage (index.html applies it pre-paint). */
export function useTheme(): [Theme, (t?: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(current)
  const setTheme = useCallback((t?: Theme) => {
    const next = t ?? (current() === 'dark' ? 'light' : 'dark')
    document.documentElement.classList.toggle('dark', next === 'dark')
    try {
      localStorage.setItem('theme', next)
    } catch {
      /* storage unavailable */
    }
    setThemeState(next)
  }, [])
  return [theme, setTheme]
}
