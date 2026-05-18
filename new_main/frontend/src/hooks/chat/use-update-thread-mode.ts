import { useMutation } from "@tanstack/react-query"
import { chatService } from "@/services/chat.service"
import { useChatStore } from "@/stores/chat.store"
import { ThreadModeUpdatePayload, RecommendedQuestion } from "@/types/chat.types"
import type { SessionMode } from "./use-chat-stream"
import { appConfig } from "@/config/app.config"

const FAQ_MODES = new Set(["faq_visitor", "faq_exhibitor"])
const FAQ_USER_MAP: Record<string, string> = {
  faq_visitor: "visitor",
  faq_exhibitor: "exhibitor",
}

async function fetchQuickmenuItems(mode: string): Promise<RecommendedQuestion[]> {
  const qa_user = FAQ_USER_MAP[mode]
  if (!qa_user) return []
  try {
    const res = await fetch(
      `${appConfig.api.baseURL}/tools/embedding/api/qa-quickmenu/primary?qa_user=${qa_user}`
    )
    if (!res.ok) return []
    const data = await res.json()
    return ((data.items ?? []) as Array<{ qna_code: string; quickmenu_display_label?: string; quickmenu_label?: string; question_sample?: string }>)
      .slice(0, 8)
      .map((item) => ({
        id: item.qna_code,
        question: item.question_sample || item.quickmenu_display_label || item.quickmenu_label || item.qna_code,
        label: item.quickmenu_display_label || item.quickmenu_label || item.qna_code,
      }))
  } catch {
    return []
  }
}

export function useUpdateThreadMode() {
  const { addMessage, setSessionMode } = useChatStore()

  return useMutation({
    mutationFn: ({ threadId, payload }: { threadId: string; payload: ThreadModeUpdatePayload }) =>
      chatService.updateThreadMode(threadId, payload),
    onSuccess: async (thread, variables) => {
      setSessionMode(thread.state.session_mode as SessionMode)

      const quickmenu = FAQ_MODES.has(variables.payload.session_mode)
        ? await fetchQuickmenuItems(variables.payload.session_mode)
        : []

      const msgs = thread.messages
      msgs.forEach((m, i) => {
        addMessage({
          id: m.id,
          type: m.role === "user" ? "question" : "answer",
          content: m.content,
          cards: m.cards,
          recommended_questions: i === msgs.length - 1 && quickmenu.length > 0 ? quickmenu : undefined,
        })
      })
    },
  })
}
