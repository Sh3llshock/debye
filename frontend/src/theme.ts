/**
 * Single source of truth for every design value (colours, fonts, sizes, radii, spacing).
 * Mapped from docs/design/v2/version-b-impeccable/tokens.json ("impeccable", Operate mode):
 * navy icon rail, tinted ground, white work areas, borders only (no shadows), Public Sans.
 * Wired into Tailwind in tailwind.config.ts. Components use classes built from these names.
 */
export const theme = {
  colors: {
    // shell (icon rail)
    rail: '#0B1F3A',
    'rail-active': '#1C3456',
    'rail-text': '#C9D3E3',
    'rail-text-active': '#FFFFFF',
    // surfaces
    bg: '#F2F5F9', // ground
    surface: '#FFFFFF', // work areas
    sub: '#EEF2F7', // sub-surface (table head, incoming bubbles, busy cells)
    line: '#DCE3EC', // the only elevation: 1px borders
    // text
    ink: '#0B1F3A',
    secondary: '#44536A',
    muted: '#66758C',
    'on-action': '#FFFFFF',
    // action (buttons, selection, current station, links)
    action: '#2E5BBA',
    'action-soft': '#E7EEFA',
    'action-dark': '#244A99',
    // state (chips and the decision row only)
    positive: '#067647',
    'positive-soft': '#E5F4EC',
    negative: '#B42318',
    'negative-soft': '#FCEBE9',
    warning: '#B54708',
    'warning-soft': '#FEF3E2',
    // lifecycle (service line)
    'life-done': '#0B1F3A',
    'life-current': '#2E5BBA',
    'life-upcoming': '#A9B6C8',
    'life-track': '#C9D3E0',
    // demo-only photo placeholder
    'photo-bg': '#13233D',
    'photo-display': '#A9C49A',
  },
  fonts: {
    sans: ['"Public Sans"', 'system-ui', 'sans-serif'],
  },
  // Role scale 30 / 18 / 16 / 15 / 14 / 13 / 12 (converted to rem in tailwind.config.ts so ?stage scales text).
  fontSize: {
    page: ['30px', { lineHeight: '36px', letterSpacing: '-0.01em' }],
    stat: ['30px', { lineHeight: '36px', letterSpacing: '-0.01em' }],
    panel: ['18px', { lineHeight: '27px' }],
    body: ['16px', { lineHeight: '24px' }],
    'body-sm': ['15px', { lineHeight: '22px' }],
    label: ['14px', { lineHeight: '21px' }],
    meta: ['13px', { lineHeight: '19px' }],
    tiny: ['12px', { lineHeight: '16px' }],
  } as Record<string, [string, { lineHeight: string; letterSpacing?: string }]>,
  radius: {
    none: '0px',
    chip: '6px',
    DEFAULT: '8px', // controls
    panel: '12px',
    full: '9999px',
  },
  shadow: {
    none: 'none',
    pop: '0 8px 24px rgba(11, 31, 58, 0.16)', // floating demo panel only, not part of the page design
  },
  spacing: {
    rail: '72px',
    header: '64px',
    work: '24px',
    inspector: '360px',
    conversation: '360px',
    row: '64px',
  },
  motion: {
    easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
    hover: '140ms',
  },
}

/** State chip colours (text in state colour on its soft tint). Unknown statuses use the neutral sub tint. */
export const chipColors = {
  positive: { fg: theme.colors.positive, bg: theme.colors['positive-soft'] },
  negative: { fg: theme.colors.negative, bg: theme.colors['negative-soft'] },
  warning: { fg: theme.colors.warning, bg: theme.colors['warning-soft'] },
  action: { fg: theme.colors.action, bg: theme.colors['action-soft'] },
  neutral: { fg: theme.colors.secondary, bg: theme.colors.sub },
}
export type ChipTone = keyof typeof chipColors
