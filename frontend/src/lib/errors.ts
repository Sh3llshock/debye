import { getLang, t } from './i18n'
// Error codes are always explained, meaning first: "Ignition failed (F.28)", never a bare "F.28".
// Uses the API's error_label when present, else this local map, else the asset's error_meaning.
const LOCAL: Record<string, string> = {
  'F.28': 'Ignition failed',
  'F.22': 'Water pressure too low',
  'F.29': 'Flame lost',
}
// German labels for the known codes (the API label is English).
const LOCAL_DE: Record<string, string> = {
  'F.28': 'Zündung fehlgeschlagen: keine Flamme beim Start',
  'F.22': 'Wasserdruck zu niedrig',
  'F.29': 'Flamme während des Betriebs erloschen',
}

/** The API's error_label ("Ignition failed: no flame at start-up"), else the local map, else error_meaning.
 *  `short` keeps only the part before the colon, for titles and captions. */
export function errorLabel(code?: string | null, label?: string | null, meaning?: string | null, short = false): string | null {
  if (!code) return null
  const l = (getLang() === 'de' && LOCAL_DE[code]) || label?.trim() || LOCAL[code] || meaning?.split(/[(,]/)[0].trim()
  if (!l) return null
  return short ? l.split(':')[0].trim() : l
}

/** "Ignition failed (F.28)"; just "Error F.28" if nothing is known about the code. */
export function errorText(code?: string | null, label?: string | null, meaning?: string | null, short = false): string | null {
  if (!code) return null
  const l = errorLabel(code, label, meaning, short)
  return l ? `${l} (${code})` : t('Error {code}', { code })
}

/** Short job title: "No heating · ignition failed (F.28)". */
export function jobTitle(title: string, code?: string | null, label?: string | null, meaning?: string | null) {
  const base = title.split(' – ')[0].split(',')[0]
  const e = errorText(code, label, meaning, true)
  return e ? `${base} · ${getLang() === "de" ? e : e.charAt(0).toLowerCase() + e.slice(1)}` : title
}

/** Explain bare codes inside free text (activity summaries): "F.28" → "ignition failed (F.28)". */
export function explainCodes(text: string): string {
  return text.replace(/\b(F\.\d{2})\b(?!\))/g, (code, _c, offset: number, whole: string) => {
    const l = errorLabel(code, null, null, true)
    if (!l || whole.toLowerCase().includes(l.toLowerCase())) return code
    // already preceded by an opening bracket, e.g. "(F.28" → leave
    if (whole[offset - 1] === '(') return code
    return `${getLang() === "de" ? l : l.toLowerCase()} (${code})`
  })
}
