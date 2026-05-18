"use client"

import { AnimatePresence } from "motion/react"
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"
import { ChatResponse } from "@/components/shared/chat-response"
import { Header } from "@/components/shared/header"
import { SessionMode, useBootstrapThread, useChatStream, useUpdateThreadMode } from "@/hooks/chat"
import { generateId } from "@/lib/utils"
import { useChatStore } from "@/stores/chat.store"
import { ChatInput, IntroOverlay, MessageList } from "./components"

export function HomeView() {
  const [inputValue, setInputValue] = useState("")
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const userScrolledUpRef = useRef(false)

  const persistApi = useChatStore.persist
  const hasHydrated = useSyncExternalStore(
    persistApi?.onFinishHydration ?? (() => () => {}),
    () => persistApi?.hasHydrated() ?? false,
    () => false
  )
  const isInitializedRef = useRef(false)

  const { threadId, sessionMode, messages, setMessages, setSessionMode, addMessage } = useChatStore()

  const { error, isStreaming, currentStreamingMessage, currentStage, currentStageMessage, sendMessage, sendCardDetail } = useChatStream()

  const { mutateAsync: bootstrapThread } = useBootstrapThread()
  const { mutateAsync: updateThreadMode } = useUpdateThreadMode()

  // On first hydration, initialise messages from Zustand persisted state.
  // The backend does not store thread history, so we skip server reload.
  useEffect(() => {
    if (!hasHydrated || isInitializedRef.current) return
    isInitializedRef.current = true

    if (!messages) {
      setMessages([])
    }
  }, [hasHydrated, messages, setMessages])

  // Reset scroll lock when streaming starts
  useEffect(() => {
    if (isStreaming) userScrolledUpRef.current = false
  }, [isStreaming])

  // Auto-scroll to bottom during streaming (instant, not smooth)
  useEffect(() => {
    if (userScrolledUpRef.current) return
    const el = scrollContainerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, isStreaming, currentStreamingMessage])

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current
    if (!el || !isStreaming) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    userScrolledUpRef.current = distanceFromBottom > 80
  }, [isStreaming])

  const handleSelectMode = useCallback(
    async (mode: SessionMode) => {
      try {
        if (threadId) {
          await updateThreadMode({ threadId, payload: { session_mode: mode } })
        } else {
          setSessionMode(mode)
          await bootstrapThread({
            event_slug: "kprint-2025",
            event_year: 2025,
            session_mode: mode,
          })
        }
      } catch (err) {
        console.error("Failed to switch mode:", err)
      }
    },
    [bootstrapThread, updateThreadMode, setSessionMode, threadId]
  )

  const handleSend = useCallback(async () => {
    const text = inputValue.trim()
    if (!text || !threadId || isStreaming) return
    setInputValue("")
    await sendMessage(text)
  }, [inputValue, isStreaming, sendMessage, threadId])

  const handleSendQuestion = useCallback(
    async (question: string) => {
      if (isStreaming || !threadId) return
      await sendMessage(question)
    },
    [isStreaming, sendMessage, threadId]
  )

  const showOverlay = hasHydrated && !threadId
  const showInput = hasHydrated && !!threadId

  return (
    <div className="relative flex h-screen max-w-lg flex-col overflow-hidden bg-white">
      <Header />

      {/* Message feed */}
      <div ref={scrollContainerRef} onScroll={handleScroll} className="flex flex-1 flex-col overflow-y-auto bg-slate-50/80 px-4 pb-32 pt-3 sm:px-5">
        <ul className="flex w-full flex-col gap-6">
          {threadId && messages && (
            <MessageList
              messages={messages}
              onSendQuestion={handleSendQuestion}
              onCardDetail={sendCardDetail}
              onSelectMode={handleSelectMode}
              currentMode={sessionMode}
            />
          )}
        </ul>

        {isStreaming && (
          <div className="mt-2 w-full px-0">
            <ChatResponse
              content={currentStreamingMessage || null}
              isStreaming
              stageMessage={currentStageMessage}
            />
          </div>
        )}

        {error && (
          <p className="mt-5 text-center text-sm text-red-500">{error}</p>
        )}

        <div ref={messagesEndRef} />
      </div>

      {showInput && (
        <ChatInput
          value={inputValue}
          disabled={isStreaming}
          onChange={setInputValue}
          onSubmit={handleSend}
        />
      )}

      <AnimatePresence>
        {showOverlay && <IntroOverlay onSelectMode={(mode) => void handleSelectMode(mode)} />}
      </AnimatePresence>
    </div>
  )
}
