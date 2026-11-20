// EN / DE for all UI copy. English is the source text and the key; German lives in ./de.ts.
// Data from the API (case titles, event summaries) and WhatsApp messages are shown as sent.
import { useSyncExternalStore } from 'react'
import { DE } from './de'

export type Lang = 'en' | 'de'
const KEY = 'debye-lang'

function initial(): Lang {
  try {
    const q = new URLSearchParams(location.search).get('lang')
    if (q === 'de' || q === 'en') return q
    return localStorage.getItem(KEY) === 'de' ? 'de' : 'en'
  } catch {
    return 'en'
  }
}

let lang: Lang = initial()
const listeners = new Set<() => void>()
document.documentElement.lang = lang

export function getLang(): Lang {
  return lang
}

export function setLang(l: Lang) {
  lang = l
  document.documentElement.lang = l
  try {
    localStorage.setItem(KEY, l)
  } catch {
    /* private mode: the choice lasts for this page only */
  }
  listeners.forEach((f) => f())
}

/** Subscribe the calling component (use it once at the app root so the whole tree re-renders). */
export function useLang(): [Lang, (l: Lang) => void] {
  const l = useSyncExternalStore(
    (f) => {
      listeners.add(f)
      return () => listeners.delete(f)
    },
    () => lang,
  )
  return [l, setLang]
}

/** Translate an English source string; `{name}` placeholders are filled from vars. */
export function t(en: string, vars?: Record<string, string | number | null | undefined>): string {
  const s = lang === 'de' ? (DE[en] ?? en) : en
  if (!vars) return s
  return s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ''))
}

/** Locale for dates and numbers. */
export const locale = () => (lang === 'de' ? 'de-DE' : 'en-GB')
