/**
 * Single source of truth for every design value (colours, fonts, sizes, radii, spacing).
 * Mapped from the client's final v3 mockups (docs/design/v3/*.html): wine palette on a warm
 * off-white ground, Inter, pill buttons and chips, 16px cards with a 1px hairline ring.
 * Wired into Tailwind in tailwind.config.ts. Components use classes built from these names.
 *
 * The old token names (action, positive, sub, …) are kept and now carry the v3 values, so every
 * page picks up the new look. The v3 names (wine, beige, ok, warn, red, blue, …) are aliases for
 * new code; the CSS variables in index.css carry the same values for the tenant portal.
 */
const v3 = {
  bg: '#FAF8F5',
  surface: '#FDFCFA',
  ink: '#2B1018',
  secondary: '#5A4744', // the mockups' --body (named secondary: text-body is a font size)
  muted: '#8E807A',
  line: 'rgba(74,20,36,.10)',
  wine: '#6B1F33',
  'wine-d': '#571828',
  'wine-tint': '#F5EBED',
  beige: '#EFE8DF',
  'beige-d': '#E2D8CB',
  ok: '#2F7D4F',
  'ok-tint': '#E7F3EB',
  'ok-line': '#BFDCC9',
  warn: '#B04A12',
  'warn-tint': '#FBEDE3',
  red: '#C0262D',
  'red-tint': '#FCE9EA',
  blue: '#34508C',
  'blue-tint': '#E9EEF8',
  cream: '#FDFAF7', // text on wine
  // WhatsApp-style chat in the staff inbox
  'chat-bg': '#EFEAE2',
  'chat-out': '#D9FDD3',
  'wa-tint': '#E6F4EA',
  'wa-text': '#1E7A35',
}

export const theme = {
  colors: {
    ...v3,
    // legacy shell names (top bar now; the old navy rail is gone)
    rail: v3.ink,
    'rail-active': v3['wine-tint'],
    'rail-text': v3.secondary,
    'rail-text-active': v3.cream,
    // surfaces
    sub: v3.beige, // sub-surface (table head, incoming bubbles, busy cells)
    // text
    'on-action': v3.cream,
    // action (buttons, selection, current station, links)
    action: v3.wine,
    'action-soft': v3['wine-tint'],
    'action-dark': v3['wine-d'],
    // state
    positive: v3.ok,
    'positive-soft': v3['ok-tint'],
    negative: v3.red,
    'negative-soft': v3['red-tint'],
    warning: v3.warn,
    'warning-soft': v3['warn-tint'],
    // lifecycle (case progress): done = green, current = wine, upcoming = beige
    'life-done': v3.ok,
    'life-current': v3.wine,
    'life-upcoming': v3['beige-d'],
    'life-track': v3['beige-d'],
    // demo-only photo placeholder
    'photo-bg': '#2B1018',
    'photo-display': '#A9C49A',
  },
  fonts: {
    // TODO(slop:F22) Inter is the only face: add a deliberate display face (fonts.display) and apply it to h1-h4
    sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Helvetica Neue"', 'Arial', 'sans-serif'],
    mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
  },
  // v3 scale: page 30/700, card title 16, body 14, meta 12–13 (rem in tailwind.config.ts so ?stage scales text).
  fontSize: {
    page: ['30px', { lineHeight: '36px', letterSpacing: '-0.02em' }],
    stat: ['26px', { lineHeight: '32px', letterSpacing: '-0.02em' }],
    title: ['24px', { lineHeight: '30px', letterSpacing: '-0.02em' }],
    head: ['20px', { lineHeight: '26px', letterSpacing: '-0.02em' }],
    panel: ['16px', { lineHeight: '22px', letterSpacing: '-0.01em' }],
    body: ['14px', { lineHeight: '21px' }],
    'body-sm': ['13.5px', { lineHeight: '20px' }],
    label: ['13px', { lineHeight: '19px' }],
    meta: ['12px', { lineHeight: '17px' }],
    tiny: ['11px', { lineHeight: '15px' }],
  } as Record<string, [string, { lineHeight: string; letterSpacing?: string }]>,
  radius: {
    none: '0px',
    chip: '980px', // pills
    sm: '6px',
    DEFAULT: '10px', // inputs, small tiles
    tile: '14px',
    panel: '16px',
    full: '9999px',
  },
  shadow: {
    none: 'none',
    card: '0 0 0 1px rgba(74,20,36,.10), 0 1px 3px rgba(43,16,24,.03)',
    ring: '0 0 0 1px rgba(74,20,36,.10)',
    lift: '0 0 0 1px rgba(74,20,36,.10), 0 8px 28px rgba(107,31,51,.08)',
    rec: '0 0 0 2px #6B1F33, 0 6px 18px rgba(107,31,51,.10)',
    bubble: '0 1px .5px rgba(0,0,0,.1)',
    pop: '0 8px 24px rgba(43,16,24,.16)', // floating demo panel
  },
  spacing: {
    rail: '72px',
    header: '57px',
    work: '28px',
    inspector: '400px',
    conversation: '380px',
    row: '64px',
  },
  motion: {
    easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
    hover: '140ms',
  },
}

/** State chip colours (text in state colour on its soft tint). Unknown statuses use beige. */
export const chipColors = {
  positive: { fg: v3.ok, bg: v3['ok-tint'] },
  negative: { fg: v3.red, bg: v3['red-tint'] },
  warning: { fg: v3.warn, bg: v3['warn-tint'] },
  action: { fg: v3.wine, bg: v3['wine-tint'] },
  blue: { fg: v3.blue, bg: v3['blue-tint'] },
  neutral: { fg: v3.secondary, bg: v3.beige },
}
export type ChipTone = keyof typeof chipColors
