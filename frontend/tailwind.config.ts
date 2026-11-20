import type { Config } from 'tailwindcss'
import { theme } from './src/theme'

// px → rem (16px root), so the stage text-size control (src/lib/stage.ts) can scale all text
// by changing the root font size. Values themselves still come from theme.ts.
const rem = (v: string) => (v.endsWith('px') ? `${parseFloat(v) / 16}rem` : v)
const fontSize = Object.fromEntries(
  Object.entries(theme.fontSize).map(([k, [size, opts]]) => [k, [rem(size), { ...opts, lineHeight: rem(opts.lineHeight) }]]),
) as typeof theme.fontSize

// All design values come from src/theme.ts. Do not add colours/sizes here.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    colors: { transparent: 'transparent', current: 'currentColor', ...theme.colors },
    fontFamily: theme.fonts,
    fontSize,
    borderRadius: theme.radius,
    boxShadow: theme.shadow,
    extend: { spacing: theme.spacing },
  },
} satisfies Config
