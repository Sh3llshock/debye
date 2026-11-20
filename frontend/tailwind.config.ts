import type { Config } from 'tailwindcss'
import { theme } from './src/theme'

// All design values come from src/theme.ts. Do not add colours/sizes here.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    colors: { transparent: 'transparent', current: 'currentColor', ...theme.colors },
    fontFamily: theme.fonts,
    fontSize: theme.fontSize,
    borderRadius: theme.radius,
    boxShadow: theme.shadow,
    extend: { spacing: theme.spacing },
  },
} satisfies Config
