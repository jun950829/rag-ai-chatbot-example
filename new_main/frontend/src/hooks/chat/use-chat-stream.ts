import { useCallback, useState } from "react"

import { generateId } from "@/lib/utils"
import { chatService } from "@/services/chat.service"
import { useChatStore } from "@/stores/chat.store"
import type { CatalogCard } from "@/types/chat.types"

export type SessionMode = "catalog" | "faq_visitor" | "faq_exhibitor"

interface SSEEvent {
  event: string
  data: string
}

interface UseChatStreamOptions {
  top_k?: number
  lang?: string
}

function parseSSEEvent(line: string): SSEEvent | null {
  if (line.startsWith("event:")) return { event: line.slice(6).trim(), data: "" }
  if (line.startsWith("data:")) return { event: "", data: line.slice(5).trim() }
  return null
}

interface BackendCard {
  title?: string
  subtitle?: string
  entity_kind?: string
  follow_prompt?: string
  external_id?: string | null
  image_url?: string | null
  website?: string | null
}

function mapBackendCard(raw: BackendCard): CatalogCard {
  const kind = (raw.entity_kind || "").toLowerCase()
  return {
    entity_type: kind === "exhibit_item" ? "product" : "company",
    entity_id: raw.external_id || "",
    external_id: raw.external_id || "",
    name: raw.title || "",
    company_name: null,
    booth_number: null,
    hall: null,
    website: raw.website || null,
    contact: null,
    category: raw.subtitle || null,
    description: null,
    image_url: raw.image_url || null,
    score: 0,
  }
}

export const useChatStream = (options?: UseChatStreamOptions) => {
  const [error, setError] = useState<string | null>(null)

  const {
    threadId,
    sessionMode,
    isStreaming,
    currentStreamingMessage,
    currentStage,
    currentStageMessage,
    startStreaming,
    updateStreamingMessage,
    setStage,
    finishStreaming,
    resetStreaming,
    addMessage,
  } = useChatStore()

  const consumeSSEStream = useCallback(
    async (stream: ReadableStream<Uint8Array>) => {
      const reader = stream.getReader()
      const decoder = new TextDecoder()

      let buffer = ""
      let currentEvent = ""
      let accumulatedContent = ""
      let pendingCards: CatalogCard[] = []

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          const blocks = buffer.split(/\n\n/)
          buffer = blocks.pop() ?? ""

          for (const block of blocks) {
            const lines = block.trim().split("\n")

            for (const line of lines) {
              if (!line.trim() || line === ": ping") continue

              const parsed = parseSSEEvent(line)
              if (!parsed) continue

              if (parsed.event) {
                currentEvent = parsed.event
              } else if (parsed.data && currentEvent) {
                try {
                  switch (currentEvent) {
                    case "stage": {
                      const stageData = JSON.parse(parsed.data)
                      setStage(stageData.name, stageData.operation ?? "")
                      break
                    }
                    case "delta": {
                      const token: string = JSON.parse(parsed.data)
                      accumulatedContent += token
                      updateStreamingMessage(accumulatedContent)
                      break
                    }
                    case "cards": {
                      const rawCards: BackendCard[] = JSON.parse(parsed.data)
                      pendingCards = rawCards.map(mapBackendCard)
                      break
                    }
                    case "done": {
                      finishStreaming(
                        accumulatedContent,
                        generateId(),
                        pendingCards.length > 0 ? pendingCards : undefined,
                      )
                      break
                    }
                    case "error": {
                      const errMsg: string = JSON.parse(parsed.data)
                      console.error("SSE error event:", errMsg)
                      break
                    }
                    case "final": {
                      const finalData = JSON.parse(parsed.data) as {
                        answer: string
                        message_id: string
                        cards?: CatalogCard[]
                        show_catalog_mode_switcher?: boolean
                      }
                      const fc = finalData.cards
                      finishStreaming(
                        finalData.answer,
                        finalData.message_id,
                        Array.isArray(fc) && fc.length > 0 ? fc : undefined,
                        {
                          showCatalogModeSwitcher: finalData.show_catalog_mode_switcher === true,
                        },
                      )
                      break
                    }
                  }
                } catch (parseError) {
                  console.error("Failed to parse SSE data:", parseError)
                }
                currentEvent = ""
              }
            }
          }
        }
      } finally {
        reader.releaseLock()
      }
    },
    [finishStreaming, setStage, updateStreamingMessage]
  )

  const runStream = useCallback(
    async (resolveStream: () => Promise<ReadableStream<Uint8Array>>) => {
      if (!threadId) {
        setError("No thread ID available")
        return
      }

      setError(null)
      startStreaming()
      try {
        const stream = await resolveStream()
        await consumeSSEStream(stream)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Stream failed")
        resetStreaming()
      }
    },
    [consumeSSEStream, resetStreaming, startStreaming, threadId]
  )

  const sendMessage = useCallback(
    async (message: string) => {
      if (!threadId) {
        setError("No thread ID available")
        return
      }

      addMessage({ id: generateId(), type: "question", content: message })

      await runStream(() =>
        chatService.streamMessage(threadId, {
          message,
          lang: options?.lang,
          top_k: options?.top_k,
          session_mode: sessionMode,
        })
      )
    },
    [addMessage, options, runStream, sessionMode, threadId]
  )

  const sendCardDetail = useCallback(
    async (card: CatalogCard) => {
      if (!threadId) {
        setError("No thread ID available")
        return
      }

      addMessage({ id: generateId(), type: "question", content: `${card.name} 자세히 보기` })

      const entityKind = card.entity_type === "product" ? "exhibit_item" : "exhibitor"

      await runStream(() =>
        chatService.streamCardDetail(threadId, card.external_id, entityKind)
      )
    },
    [addMessage, runStream, threadId]
  )

  return {
    error,
    isStreaming,
    currentStage,
    currentStageMessage,
    currentStreamingMessage,
    sendMessage,
    sendCardDetail,
  }
}
