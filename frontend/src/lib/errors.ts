// Error codes are always explained, meaning first: "Ignition failed (F.28)", never a bare "F.28".
// Uses the API's error_label when present, else this local map, else the asset's error_meaning.
const LOCAL: Record<string, string> = {
  'F.28': 'Ignition failed',
  'F.22': 'Water pressure too low',
  'F.29': 'Flame lost',
}

export function errorLabel(code?: string | null, label?: string | null, meaning?: string | null): string | null {
  if (!code) return null
  const l = label?.trim() || LOCAL[code] || meaning?.split(/[(,]/)[0].trim()
  return l || null
}

/** "Ignition failed (F.28)"; just "Error F.28" if nothing is known about the code. */
export function errorText(code?: string | null, label?: string | null, meaning?: string | null): string | null {
  if (!code) return null
  const l = errorLabel(code, label, meaning)
  return l ? `${l} (${code})` : `Error ${code}`
}

/** Short job title: "No heating · ignition failed (F.28)". */
export function jobTitle(title: string, code?: string | null, label?: string | null, meaning?: string | null) {
  const base = title.split(' – ')[0].split(',')[0]
  const e = errorText(code, label, meaning)
  return e ? `${base} · ${e.charAt(0).toLowerCase()}${e.slice(1)}` : title
}

/** Explain bare codes inside free text (activity summaries): "F.28" → "ignition failed (F.28)". */
export function explainCodes(text: string): string {
  return text.replace(/\b(F\.\d{2})\b(?!\))/g, (code, _c, offset: number, whole: string) => {
    const l = LOCAL[code]
    if (!l || whole.toLowerCase().includes(l.toLowerCase())) return code
    // already preceded by an opening bracket, e.g. "(F.28" → leave
    if (whole[offset - 1] === '(') return code
    return `${l.toLowerCase()} (${code})`
  })
}
