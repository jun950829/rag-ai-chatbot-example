import type { HubMode } from '@/domain/types'

const MODES: { id: HubMode; label: string }[] = [
  { id: 'visitor_faq', label: '참관객 FAQ' },
  { id: 'exhibitor_faq', label: '참가업체 FAQ' },
  { id: 'company_rag', label: '기업/제품 정보' },
]

type Props = {
  value: HubMode
  onChange: (m: HubMode) => void
  compact?: boolean
}

export function ModeSelect({ value, onChange, compact }: Props) {
  return (
    <div
      className={
        compact
          ? 'flex flex-wrap justify-center gap-2'
          : 'flex w-full max-w-lg flex-col gap-2 sm:flex-row sm:justify-center'
      }
      role="tablist"
      aria-label="검색 모드"
    >
      {MODES.map((m) => {
        const active = value === m.id
        return (
          <button
            key={m.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(m.id)}
            className={
              active
                ? 'rounded-full border border-slate-900 bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors'
                : 'rounded-full border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 shadow-sm transition-colors hover:border-slate-300 hover:bg-slate-50'
            }
          >
            {m.label}
          </button>
        )
      })}
    </div>
  )
}
