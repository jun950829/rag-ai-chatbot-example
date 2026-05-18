import { useState } from 'react'

import type { SuggestionCard } from '@/domain/types'

function Thumb({ imgUrl, entityKind }: { imgUrl: string; entityKind: string }) {
  const [broken, setBroken] = useState(false)
  const fallback =
    entityKind === 'exhibit_item' ? '이미지 없음 · 제품' : '이미지 없음 · 기업'
  return (
    <div className="flex h-[100px] items-center justify-center overflow-hidden rounded-lg bg-slate-200">
      {imgUrl && !broken ? (
        <img
          src={imgUrl}
          alt=""
          className="h-full w-full object-contain"
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setBroken(true)}
        />
      ) : (
        <span className="text-xs font-semibold text-slate-500">{fallback}</span>
      )}
    </div>
  )
}

type Props = {
  cards: SuggestionCard[]
  onDetail: (card: SuggestionCard) => void
}

export function SuggestionCarousel({ cards, onDetail }: Props) {
  if (!cards.length) return null
  return (
    <div className="w-full overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <div className="flex gap-3 pr-1">
        {cards.map((c, idx) => {
          const imgUrl = String(c.image_url || '').trim()
          const kind = String(c.entity_kind || '')
          return (
            <article
              key={`${c.title || ''}-${idx}`}
              className="flex w-[min(268px,85vw)] shrink-0 snap-start flex-col gap-2 rounded-xl border border-slate-200 bg-slate-50 p-2.5 shadow-sm"
            >
              <Thumb imgUrl={imgUrl} entityKind={kind} />
              <div className="text-sm font-bold leading-snug text-slate-900">{c.title || ''}</div>
              <div className="line-clamp-3 text-xs leading-relaxed text-slate-600">{c.subtitle || ''}</div>
              <button
                type="button"
                onClick={() => onDetail(c)}
                className="mt-auto rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-900 hover:bg-slate-50"
              >
                자세히 보기
              </button>
            </article>
          )
        })}
      </div>
    </div>
  )
}
