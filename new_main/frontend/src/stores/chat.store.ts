import { create } from "zustand"
import { persist } from "zustand/middleware"
import { SessionMode } from "@/hooks/chat"
import { CatalogCard, RecommendedQuestion } from "@/types/chat.types"

export interface Message {
  id: string
  type: "question" | "answer"
  content: string
  isStreaming?: boolean
  stage?: string
  session_mode?: SessionMode
  stageMessage?: string
  feedback?: "like" | "dislike" | null
  cards?: CatalogCard[]
  recommended_questions?: RecommendedQuestion[]
  selected_recommended_question_id?: string | null
  /** FAQ 미매칭 + 제품/업체 휴리스틱일 때만: 답변 아래 검색 모드 전환 UI 표시 */
  show_catalog_mode_switcher?: boolean
}

interface ChatState {
  threadId: string | null
  sessionMode: SessionMode
  messages: Message[] | null
  currentStreamingMessage: string | null
  currentStage: string | null
  currentStageMessage: string | null
  isStreaming: boolean
  setThreadId: (threadId: string | null) => void
  setSessionMode: (mode: SessionMode) => void
  addMessage: (message: Message) => void
  setMessages: (messages: Message[]) => void
  updateStreamingMessage: (content: string) => void
  setStage: (stage: string, message: string) => void
  startStreaming: () => void
  finishStreaming: (
    finalContent: string,
    responseId: string,
    cards?: CatalogCard[],
    opts?: { showCatalogModeSwitcher?: boolean },
  ) => void
  resetStreaming: () => void
  clearMessages: () => void
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      threadId: null,
      sessionMode: "catalog",
      messages: null,
      currentStreamingMessage: "",
      currentStage: null,
      currentStageMessage: null,
      isStreaming: false,

      setThreadId: (threadId) => set({ threadId }),
      setSessionMode: (sessionMode) => set({ sessionMode }),

      addMessage: (message) =>
        set((state) => ({
          messages: state.messages ? [...state.messages, message] : [message],
        })),

      setMessages: (messages) => set({ messages }),

      updateStreamingMessage: (content) => set({ currentStreamingMessage: content }),

      setStage: (stage, message) => set({ currentStage: stage, currentStageMessage: message }),

      startStreaming: () =>
        set({
          isStreaming: true,
          currentStreamingMessage: "",
          currentStage: null,
          currentStageMessage: null,
        }),

      finishStreaming: (finalContent, responseId, cards, opts) =>
        set((state) => {
          const msg: Message = {
            id: responseId,
            type: "answer",
            content: finalContent,
          }
          if (cards && cards.length > 0) {
            msg.cards = cards
          }
          if (opts?.showCatalogModeSwitcher === true) {
            msg.show_catalog_mode_switcher = true
          }
          return {
            isStreaming: false,
            currentStreamingMessage: "",
            currentStage: null,
            currentStageMessage: null,
            messages: state.messages ? [...state.messages, msg] : null,
          }
        }),

      resetStreaming: () =>
        set({
          isStreaming: false,
          currentStreamingMessage: "",
          currentStage: null,
          currentStageMessage: null,
        }),

      clearMessages: () => set({ messages: [] }),
    }),
    {
      name: "chat-storage",
      partialize: (state) => ({
        threadId: state.threadId,
        sessionMode: state.sessionMode,
      }),
    }
  )
)

/** localStorage `chat-storage` 제거 + 인메모리 상태를 초기(카테고리 선택 화면)로 되돌림 */
export function resetChatToHome(): void {
  void useChatStore.persist.clearStorage()
  useChatStore.setState({
    threadId: null,
    sessionMode: "catalog",
    messages: null,
    currentStreamingMessage: "",
    currentStage: null,
    currentStageMessage: null,
    isStreaming: false,
  })
}
