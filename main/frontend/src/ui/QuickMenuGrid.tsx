import { quickmenuDisplayLabel } from '@/domain/quickmenu'
import type { QuickmenuItem } from '@/domain/types'

const ACCENTS = ['bg-amber-100 text-amber-800', 'bg-orange-100 text-orange-800', 'bg-sky-100 text-sky-800', 'bg-violet-100 text-violet-800', 'bg-emerald-100 text-emerald-800', 'bg-rose-100 text-rose-800']

type Props = {
  items: QuickmenuItem[]
  onPick: (item: QuickmenuItem) => void
}

export function QuickMenuGrid({ items, onPick }: Props) {
  if (!items.length) return null
  return (
    <div className="grid w-full max-w-lg grid-cols-1 gap-3 sm:grid-cols-2">
      {items.map((item, i) => {
        const label = quickmenuDisplayLabel(item) || item.qna_code
        const ch = label.slice(0, 1) || '?'
        const accent = ACCENTS[i % ACCENTS.length]!
        return (
          <button
            key={item.qna_code}
            type="button"
            onClick={() => onPick(item)}
            className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3.5 text-left shadow-sm transition-colors hover:border-slate-300 hover:bg-slate-50"
          >
            <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-lg font-bold ${accent}`}>{ch}</span>
            <span className="min-w-0 flex-1 text-sm font-semibold leading-snug text-slate-900">{label}</span>
            <span className="shrink-0 text-slate-300" aria-hidden>
              ›
            </span>
          </button>
        )
      })}
    </div>
  )
}
