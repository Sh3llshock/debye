/**
 * Single source of truth for every design value (colours, fonts, sizes, radii, spacing).
 * Wired into Tailwind in tailwind.config.ts. Components use Tailwind classes built from
 * these names (bg-surface, text-plum, rounded-card, text-body ...), never raw values.
 *
 * Placeholder values sampled from https://www.reltix.de/ (cream background, deep plum,
 * Baskervville headings, IBM Plex Sans body). Replace with docs/design/tokens.json when it lands.
 */
export const theme = {
  colors: {
    // surfaces
    bg: '#FCF6EF', // page background (reltix cream)
    surface: '#FFFFFF', // cards
    'surface-alt': '#FAF6F2', // secondary panels
    line: '#E8DED3', // borders, dividers
    // text
    ink: '#1A1018',
    muted: '#6E6470',
    'on-plum': '#FFFFFF',
    // brand
    plum: '#330933', // primary (reltix headings)
    'plum-dark': '#290629',
    'plum-soft': '#F1E6F0', // tinted background for plum accents
    // status
    success: '#1F7A4D',
    'success-soft': '#E3F3EA',
    warning: '#A35C00',
    'warning-soft': '#FCEFD9',
    danger: '#B42318',
    'danger-soft': '#FDE7E5',
    info: '#1F5AA6',
    'info-soft': '#E4EDFA',
    // WhatsApp thread preview
    'wa-in': '#FFFFFF',
    'wa-out': '#DCF8C6',
    'wa-bg': '#EFE7DD',
  },
  fonts: {
    serif: ['Baskervville', 'Georgia', 'serif'],
    sans: ['"IBM Plex Sans"', 'Inter', 'system-ui', 'sans-serif'],
    mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
  },
  // Projector-first scale: body is 18px so it reads from the back of the hall.
  fontSize: {
    xs: ['14px', { lineHeight: '20px' }],
    sm: ['16px', { lineHeight: '24px' }],
    body: ['18px', { lineHeight: '28px' }],
    lg: ['22px', { lineHeight: '30px' }],
    xl: ['28px', { lineHeight: '36px' }],
    '2xl': ['36px', { lineHeight: '44px' }],
    '3xl': ['48px', { lineHeight: '56px' }],
  } as Record<string, [string, { lineHeight: string }]>,
  radius: {
    none: '0',
    sm: '6px',
    DEFAULT: '10px',
    card: '16px',
    pill: '40px', // reltix buttons are fully rounded
    full: '9999px',
  },
  shadow: {
    none: 'none',
    card: '0 1px 2px rgba(51, 9, 51, 0.06), 0 4px 16px rgba(51, 9, 51, 0.06)',
    pop: '0 8px 32px rgba(51, 9, 51, 0.18)',
  },
  spacing: {
    gutter: '16px',
    card: '24px',
    section: '32px',
  },
}

export type StatusTone = 'neutral' | 'info' | 'warning' | 'success' | 'danger' | 'plum'
