/**
 * Single source of truth for every design value (colours, fonts, sizes, radii, spacing).
 * Mapped from docs/design/tokens.json (designer, reltix-derived, projector scale).
 * Wired into Tailwind in tailwind.config.ts. Components use Tailwind classes built from
 * these names (bg-surface, text-plum, rounded-card, text-body ...) or, for data-driven
 * colours (status, priority, actor), read the maps below. Never hard-code values.
 */

const brand = {
  aubergine: '#330933',
  aubergineDeep: '#2A072A',
  aubergineInk: '#290629',
  aubergine80: '#5C3A5C',
  aubergine60: '#856B85',
  aubergine20: '#D6CED6',
  aubergine10: '#EBE6EB',
  aubergine05: '#F5F2F5',
  violet: '#8332AC',
  violetSoft: '#F1E6F7',
}

export const theme = {
  colors: {
    // surfaces
    bg: '#FAF6F2', // surface.page
    'bg-warm': '#FCF6EF', // surface.pageWarm
    surface: '#FFFFFF', // surface.card
    'surface-alt': '#F3EDE6', // surface.subtle
    line: '#E7DFD7', // border.default
    // text
    ink: '#1A1A1A', // text.body
    heading: '#330933',
    muted: '#6B6B6B',
    'on-plum': '#FFFFFF',
    'on-plum-muted': 'rgba(255, 255, 255, 0.72)',
    'line-on-plum': 'rgba(255, 255, 255, 0.20)',
    link: brand.violet,
    // brand
    plum: brand.aubergine,
    'plum-dark': brand.aubergineInk,
    'plum-80': brand.aubergine80,
    'plum-60': brand.aubergine60,
    'plum-20': brand.aubergine20,
    'plum-soft': brand.aubergine10,
    'plum-faint': brand.aubergine05,
    violet: brand.violet,
    'violet-soft': brand.violetSoft,
    // feedback
    success: '#1E7A46',
    'success-soft': '#E2F3E8',
    warning: '#A15C07',
    'warning-soft': '#FDF0DC',
    danger: '#B42318',
    'danger-soft': '#FDE7E5',
    info: '#1F5FA8',
    'info-soft': '#E3EEFA',
    // WhatsApp thread preview
    'wa-header': '#008069',
    'wa-in': '#FFFFFF',
    'wa-out': '#D9FDD3',
    'wa-bg': '#EFEAE2',
    'wa-meta': '#667781',
    'wa-tick': '#53BDEB',
  },
  fonts: {
    serif: ['Baskervville', '"Libre Baskerville"', 'Georgia', 'serif'],
    sans: ['"IBM Plex Sans"', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', 'sans-serif'],
    mono: ['"IBM Plex Mono"', 'ui-monospace', 'Menlo', 'monospace'],
  },
  // Projector scale from tokens.fontSize. Never below 15px.
  fontSize: {
    xs: ['15px', { lineHeight: '20px', letterSpacing: '0.01em' }], // caption
    eyebrow: ['14px', { lineHeight: '18px', letterSpacing: '0.08em' }],
    sm: ['16px', { lineHeight: '22px', letterSpacing: '0.01em' }], // label
    'body-sm': ['18px', { lineHeight: '26px' }],
    body: ['20px', { lineHeight: '30px' }],
    lg: ['24px', { lineHeight: '34px' }], // lead
    xl: ['28px', { lineHeight: '34px', letterSpacing: '-0.02em' }], // h3 (card titles)
    '2xl': ['36px', { lineHeight: '42px', letterSpacing: '-0.04em' }], // h2
    '3xl': ['48px', { lineHeight: '54px', letterSpacing: '-0.05em' }], // h1
    stat: ['56px', { lineHeight: '60px', letterSpacing: '-0.02em' }],
    display: ['64px', { lineHeight: '68px', letterSpacing: '-0.05em' }],
  } as Record<string, [string, { lineHeight: string; letterSpacing?: string }]>,
  radius: {
    none: '0px',
    sm: '8px',
    DEFAULT: '12px',
    lg: '16px',
    button: '16px',
    card: '20px',
    '2xl': '28px',
    pill: '999px',
    full: '9999px',
  },
  shadow: {
    none: 'none',
    card: '0 1px 2px rgba(51, 9, 51, 0.06), 0 6px 18px rgba(51, 9, 51, 0.06)',
    pop: '0 8px 24px rgba(51, 9, 51, 0.14)',
    button: '0 2px 4px rgba(51, 9, 51, 0.30)',
    focus: '0 0 0 3px rgba(131, 50, 172, 0.35)',
  },
  spacing: {
    gutter: '16px', // mobile page gutter
    page: '48px', // layout.pageGutter (desktop)
    gap: '32px', // layout.columnGap
    card: '32px', // layout.cardPadding
    'card-sm': '24px', // layout.cardPaddingCompact
    section: '32px',
    topbar: '80px',
  },
  motion: {
    easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
    fast: '120ms',
    base: '200ms',
    slow: '320ms',
  },
}

/** Status pill colours (tokens color.status). Unknown statuses fall back to `closed`. */
export const statusColors: Record<string, { fg: string; bg: string }> = {
  new: { fg: '#8332AC', bg: '#F1E6F7' },
  requested: { fg: '#8332AC', bg: '#F1E6F7' },
  awaiting_approval: { fg: '#A15C07', bg: '#FDF0DC' },
  accepted: { fg: '#1F5FA8', bg: '#E3EEFA' },
  slots_proposed: { fg: '#A15C07', bg: '#FDF0DC' },
  scheduled: { fg: '#1F5FA8', bg: '#E3EEFA' },
  in_progress: { fg: '#A15C07', bg: '#FDF0DC' },
  completed: { fg: '#1E7A46', bg: '#E2F3E8' },
  invoiced: { fg: '#1E7A46', bg: '#E2F3E8' },
  closed: { fg: '#4A4A4A', bg: '#EDEDED' },
  declined: { fg: '#B42318', bg: '#FDE7E5' },
}

/** Priority colours (tokens color.priority). Urgent is the only filled red element. */
export const priorityColors: Record<string, { fg: string; bg: string }> = {
  urgent: { fg: '#FFFFFF', bg: '#B42318' },
  high: { fg: '#A15C07', bg: '#FDF0DC' },
  normal: { fg: '#5C3A5C', bg: '#EBE6EB' },
  low: { fg: '#5C3A5C', bg: '#EBE6EB' },
}

/** Timeline actor circles (tokens color.actor). */
export const actorColors: Record<string, { fg: string; bg: string }> = {
  debye: { fg: '#FFFFFF', bg: '#330933' },
  tenant: { fg: '#FFFFFF', bg: '#1E7A46' },
  partner: { fg: '#FFFFFF', bg: '#A15C07' },
  staff: { fg: '#FFFFFF', bg: '#1F5FA8' },
  pm: { fg: '#FFFFFF', bg: '#1F5FA8' },
  system: { fg: '#4A4A4A', bg: '#E7DFD7' },
}

export type StatusTone = 'neutral' | 'info' | 'warning' | 'success' | 'danger' | 'plum'
