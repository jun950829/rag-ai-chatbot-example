"use client"

import { FC, useCallback, useEffect, useState } from "react"
import { Carousel, CarouselApi, CarouselContent, CarouselItem } from "@/components/ui/carousel"
import { LocationIcon, AddIcon } from "@/components/icons"
import { cn } from "@/lib/utils"
import { CatalogCard } from "@/types/chat.types"

const ArrowIcon: FC<{ direction: "left" | "right" }> = ({ direction }) => (
  <svg
    className={cn("size-4", direction === "left" ? "rotate-180" : "")}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
  >
    <path d="M5.5 3L10.5 8L5.5 13" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const CatalogCardItem: FC<{ card: CatalogCard; onDetail?: (card: CatalogCard) => void }> = ({ card, onDetail }) => {
  const [imgError, setImgError] = useState(false)

  useEffect(() => { setImgError(false) }, [card.image_url])

  return (
    <article className="flex h-full flex-col rounded-lg border border-gray-100 bg-white p-3 shadow-sm">
      {card.image_url && !imgError && (
        <figure className="relative mb-2 flex h-28 items-center justify-center overflow-hidden rounded-md bg-gray-50">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={card.image_url}
            alt={card.name}
            className="h-full w-full object-contain p-2"
            referrerPolicy="no-referrer"
            loading="lazy"
            onError={() => setImgError(true)}
          />
        </figure>
      )}

      <p className="line-clamp-2 text-sm font-semibold text-gray-900">{card.name}</p>

      {card.category && (
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-gray-500">{card.category}</p>
      )}

      <div className="mt-1 flex items-center gap-1">
        {card.booth_number && (
          <div className="flex items-center gap-0.5 rounded bg-red-50 px-1.5 py-0.5">
            <LocationIcon className="size-3 text-red-500" />
            <span className="text-xs text-red-500">{card.booth_number}</span>
          </div>
        )}
        {card.company_name && (
          <p className="truncate text-xs text-gray-400">{card.company_name}</p>
        )}
      </div>

      {onDetail && (
        <button
          type="button"
          onClick={() => onDetail(card)}
          className="mt-auto rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50"
        >
          자세히 보기
        </button>
      )}
    </article>
  )
}

const CatalogCardList: FC<{ cards: CatalogCard[]; onDetail?: (card: CatalogCard) => void }> = ({ cards, onDetail }) => {
  const [api, setApi] = useState<CarouselApi>()
  const [canScrollPrev, setCanScrollPrev] = useState(false)
  const [canScrollNext, setCanScrollNext] = useState(false)

  const updateScrollState = useCallback((carouselApi?: CarouselApi) => {
    if (!carouselApi) return
    setCanScrollPrev(carouselApi.canScrollPrev())
    setCanScrollNext(carouselApi.canScrollNext())
  }, [])

  useEffect(() => {
    if (!api) return
    updateScrollState(api)
    api.on("select", updateScrollState)
    api.on("reInit", updateScrollState)
    return () => {
      api.off("select", updateScrollState)
      api.off("reInit", updateScrollState)
    }
  }, [api, updateScrollState])

  const isMultiple = cards.length > 1

  return (
    <div className="relative mt-3 w-full">
      <Carousel setApi={setApi} opts={{ align: "start", dragFree: true, containScroll: "trimSnaps" }}>
        <CarouselContent className="-ml-2.5">
          {cards.map((card) => (
            <CarouselItem key={card.entity_id} className="basis-[75%] pl-2.5 sm:basis-[52%]">
              <CatalogCardItem card={card} onDetail={onDetail} />
            </CarouselItem>
          ))}
          {isMultiple && (
            <CarouselItem className="mr-12 basis-[28%] pl-2.5">
              <div className="flex h-full items-center justify-center">
                <button
                  type="button"
                  aria-label="More results"
                  className="flex size-11 items-center justify-center rounded-full bg-blue-600 text-white shadow-md"
                >
                  <AddIcon className="size-5" />
                </button>
              </div>
            </CarouselItem>
          )}
        </CarouselContent>
      </Carousel>

      {canScrollPrev && isMultiple && (
        <button
          type="button"
          aria-label="Previous"
          onClick={() => api?.scrollPrev()}
          className="absolute left-0 top-1/2 z-10 flex size-8 -translate-y-1/2 items-center justify-center rounded-full bg-blue-600 text-white shadow-md"
        >
          <ArrowIcon direction="left" />
        </button>
      )}
      {canScrollNext && isMultiple && (
        <button
          type="button"
          aria-label="Next"
          onClick={() => api?.scrollNext()}
          className="absolute right-0 top-1/2 z-10 flex size-8 -translate-y-1/2 items-center justify-center rounded-full bg-blue-600 text-white shadow-md"
        >
          <ArrowIcon direction="right" />
        </button>
      )}
    </div>
  )
}

export { CatalogCardList }
