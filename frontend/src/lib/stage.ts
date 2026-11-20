// Stage text size: scales all text (font sizes are rem) without touching layout spacing.
//   ?stage=1      → 110 %          ?stage=1.2 → 120 %          ?stage=0 → back to 100 %
// The choice is remembered per browser, so a reload on the projector keeps it.
const KEY = 'debye-stage-scale'
export const STAGE_MIN = 0.9
export const STAGE_MAX = 1.4

function clamp(n: number) {
  return Math.min(STAGE_MAX, Math.max(STAGE_MIN, Math.round(n * 100) / 100))
}

export function getStageScale(): number {
  try {
    const v = parseFloat(localStorage.getItem(KEY) ?? '')
    return isNaN(v) ? 1 : clamp(v)
  } catch {
    return 1
  }
}

export function setStageScale(n: number) {
  const s = clamp(n)
  document.documentElement.style.fontSize = s === 1 ? '' : `${s * 100}%`
  try {
    if (s === 1) localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, String(s))
  } catch {
    /* private mode: applies for this page only */
  }
  return s
}

/** Call once at startup: reads ?stage= (wins) or the remembered value. */
export function initStageScale() {
  const q = new URLSearchParams(location.search).get('stage')
  if (q !== null) {
    const n = parseFloat(q)
    // "1" / "true" mean "stage mode" (+10 %); a number ≥ 0.9 other than 1 is taken as the scale itself.
    const scale = q === '' || q === 'true' || n === 1 ? 1.1 : n === 0 || isNaN(n) ? 1 : n
    setStageScale(scale)
  } else {
    setStageScale(getStageScale())
  }
}
