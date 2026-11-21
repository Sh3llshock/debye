import type { ReactNode } from 'react'

export type SummaryItem = { label: string; value: ReactNode; onClick?: () => void }

/** One row of numbers separated by hairline dividers (not tiles). Items with onClick are buttons. */
export function SummaryStrip({ items, className = 'mb-4' }: { items: SummaryItem[]; className?: string }) {
  return (
    <div className={`grid grid-cols-2 rounded-panel bg-surface shadow-card md:flex ${className}`}>
      {items.map((it, i) => {
        const inner = (
          <>
            <span className="block text-label text-muted">{it.label}</span>
            <b className="mt-0.5 block font-display text-stat font-semibold">{it.value}</b>
          </>
        )
        const cls = `min-w-0 flex-1 px-5 py-3.5 text-left ${i > 0 ? 'md:border-l md:border-line' : ''} ${i % 2 === 1 ? 'border-l border-line md:border-l' : ''} ${i >= 2 ? 'border-t border-line md:border-t-0' : ''}`
        return it.onClick ? (
          <button key={it.label} onClick={it.onClick} className={`${cls} transition-colors duration-200 hover:bg-beige/40`}>
            {inner}
          </button>
        ) : (
          <div key={it.label} className={cls}>
            {inner}
          </div>
        )
      })}
    </div>
  )
}
