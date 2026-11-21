/**
 * Single source of truth for every design value (colours, fonts, sizes, radii, spacing).
 * v4 (docs/design/v4-polish): the v3 wine palette on a clearly darker paper ground with white sheets,
 * Lexend, square-ish corners (2/3/4px), keyed rectangular buttons, flat hairline surfaces, a 36/20/15/12 type scale.
 * docs/design/v4-polish/rules.html lists the "AI usually does this, Debye does this" rules.
 * Wired into Tailwind in tailwind.config.ts. Components use classes built from these names.
 *
 * The old token names (action, positive, sub, …) are kept and now carry the v3 values, so every
 * page picks up the new look. The v3 names (wine, beige, ok, warn, red, blue, …) are aliases for
 * new code; the CSS variables in index.css carry the same values for the tenant portal.
 */
const v3 = {
  bg: '#F2EDE6',
  surface: '#FFFFFF',
  ink: '#2B1018',
  secondary: '#4A3A37', // the mockups' --body (named secondary: text-body is a font size)
  muted: '#6A5B53', // 5.6:1 on bg
  line: 'rgba(74,20,36,.16)',
  wine: '#6B1F33',
  'wine-d': '#571828',
  'wine-tint': '#F3E4E8',
  beige: '#E8E0D5',
  'beige-d': '#D9CEC0',
  ok: '#2F7D4F',
  'ok-tint': '#E7F3EB',
  'ok-line': '#BFDCC9',
  warn: '#A8460F',
  'warn-tint': '#FBEDE3',
  red: '#C0262D',
  'red-tint': '#FCE9EA',
  blue: '#34508C',
  'blue-tint': '#E9EEF8',
  cream: '#FDFAF7', // text on wine
  // WhatsApp-style chat in the staff inbox
  'chat-bg': '#E9E3D9',
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
    'photo-bg': '#1E2420',
    'photo-display': '#B8F5C8',
    // the boiler display (error code) drawn as an LCD
    lcd: '#1E2420',
    'lcd-ink': '#B8F5C8',
  },
  fonts: {
    sans: ['Lexend', '-apple-system', 'BlinkMacSystemFont', '"Helvetica Neue"', 'Arial', 'sans-serif'],
    mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
  },
  // v4 scale: page 36/500, section 20, body 15, meta 12–13; weights 400/500 (rem in tailwind.config.ts so ?stage scales text).
  fontSize: {
    page: ['36px', { lineHeight: '42px', letterSpacing: '-0.02em' }],
    stat: ['44px', { lineHeight: '48px', letterSpacing: '-0.03em' }],
    title: ['28px', { lineHeight: '34px', letterSpacing: '-0.02em' }],
    head: ['20px', { lineHeight: '28px', letterSpacing: '-0.01em' }],
    panel: ['17px', { lineHeight: '24px', letterSpacing: '-0.01em' }],
    body: ['15px', { lineHeight: '24px' }],
    'body-sm': ['14px', { lineHeight: '22px' }],
    label: ['13px', { lineHeight: '20px' }],
    meta: ['12px', { lineHeight: '16px' }],
    tiny: ['11px', { lineHeight: '15px' }],
  } as Record<string, [string, { lineHeight: string; letterSpacing?: string }]>,
  radius: {
    none: '0px',
    // square-ish: no pills anywhere. full is 2px on purpose (avatars, markers, chips are squares)
    chip: '3px',
    sm: '2px',
    DEFAULT: '3px', // inputs, buttons
    tile: '4px',
    panel: '4px',
    bubble: '6px', // WhatsApp bubbles stay recognisable
    full: '2px',
  },
  shadow: {
    none: 'none',
    // flat and ruled: one floating shadow (lift) per screen at most
    card: '0 0 0 1px rgba(74,20,36,.16)',
    ring: '0 0 0 1px rgba(74,20,36,.16)',
    lift: '0 0 0 1px rgba(74,20,36,.16), 0 16px 40px rgba(43,16,24,.12)',
    rec: '0 0 0 1px rgba(74,20,36,.16)',
    key: 'inset 0 -2px 0 rgba(0,0,0,.30)', // the primary button's key edge
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
    easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
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
