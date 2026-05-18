import { appConfig } from "@/config/app.config"
import { generateId } from "@/lib/utils"
import type {
  CatalogCard,
  CreateThreadPayload,
  Thread,
  ThreadMessage,
  ThreadModeUpdatePayload,
  ThreadSummary,
} from "@/types/chat.types"

function welcomeMessages(mode: string): ThreadMessage[] {
  const base: Omit<ThreadMessage, "id" | "content"> = {
    role: "assistant",
    lang: "ko",
    cards: [],
    created_at: new Date().toISOString(),
  }
  const id = `welcome-${generateId()}`
  if (mode === "faq_visitor") {
    return [{ ...base, id, content: "안녕하세요! 전시회 관람객 FAQ 안내입니다.\n\n관람 시간, 입장료, 교통편 등 궁금한 점을 질문해 주세요." }]
  }
  if (mode === "faq_exhibitor") {
    return [{ ...base, id, content: "안녕하세요! 참가업체 FAQ 안내입니다.\n\n부스 설치, 반입/반출 일정, 전시 규정 등을 안내해 드리겠습니다." }]
  }
  return [{ ...base, id, content: "안녕하세요! KPRINT AI 어시스턴트입니다.\n\n전시회 정보나 참가기업, 제품이 궁금하시면 자유롭게 질문해 주세요." }]
}

function syntheticThread(threadId: string, mode: string): Thread {
  return {
    thread_id: threadId,
    event_slug: "",
    owner_type: null,
    owner_id: null,
    state: {
      event_slug: "",
      event_year: 0,
      session_mode: mode as Thread["state"]["session_mode"],
      active_faq_id: null,
      active_faqs: [],
      active_entity_type: null,
      active_entity_id: null,
      active_result_set_id: null,
      active_result_set_type: null,
      active_results: [],
      active_filters: {},
      last_turn_type: null,
    },
    messages: welcomeMessages(mode),
  }
}

export class ChatService {
  async createThread(payload: CreateThreadPayload): Promise<Thread> {
    const id = generateId()
    return syntheticThread(id, payload.session_mode)
  }

  async listThreads(_params: { event_slug: string; owner_type: string; owner_id: string }): Promise<ThreadSummary[]> {
    return []
  }

  async loadThread(threadId: string): Promise<Thread> {
    return syntheticThread(threadId, "catalog")
  }

  async updateThreadMode(threadId: string, payload: ThreadModeUpdatePayload): Promise<Thread> {
    return syntheticThread(threadId, payload.session_mode)
  }

  async getHealth(): Promise<{ status: string; service: string; environment: string }> {
    return { status: "ok", service: "new_main", environment: "local" }
  }

  async streamMessage(
    sessionId: string,
    payload: { message: string; lang?: string; top_k?: number; session_mode?: string }
  ): Promise<ReadableStream<Uint8Array>> {
    const fd = new FormData()
    fd.append("session_id", sessionId)
    fd.append("message", payload.message)
    if (payload.session_mode) fd.append("session_mode", payload.session_mode)

    const response = await fetch(`${appConfig.api.baseURL}/chat`, {
      method: "POST",
      headers: { Accept: "text/event-stream" },
      body: fd,
    })

    if (!response.ok || !response.body) {
      throw new Error(`Stream failed: ${response.statusText}`)
    }

    return response.body
  }

  async streamCardDetail(
    sessionId: string,
    externalId: string,
    entityKind?: string,
    language?: string
  ): Promise<ReadableStream<Uint8Array>> {
    const fd = new FormData()
    fd.append("session_id", sessionId)
    fd.append("external_id", externalId)
    if (entityKind) fd.append("entity_kind", entityKind)
    if (language) fd.append("language", language)

    const response = await fetch(`${appConfig.api.baseURL}/chat/card-detail`, {
      method: "POST",
      headers: { Accept: "text/event-stream" },
      body: fd,
    })

    if (!response.ok || !response.body) {
      throw new Error(`Stream failed: ${response.statusText}`)
    }

    return response.body
  }
}

export const chatService = new ChatService()
