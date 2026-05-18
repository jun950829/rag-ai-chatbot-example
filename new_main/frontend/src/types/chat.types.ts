import { SessionMode } from "@/hooks/chat"

export const CATALOG_QUERY_INTENTS = ["product_query", "company_query"] as const
export type CatalogQueryIntent = (typeof CATALOG_QUERY_INTENTS)[number]

// Thread-based types matching the template backend contract

export type ThreadSessionMode = "catalog" | "faq_visitor" | "faq_exhibitor"

export interface CatalogCard {
  entity_type: "company" | "product"
  entity_id: string
  external_id: string
  name: string
  company_name: string | null
  booth_number: string | null
  hall: string | null
  website: string | null
  contact: string | null
  category: string | null
  description: string | null
  image_url: string | null
  score: number
}

export interface ThreadState {
  event_slug: string
  event_year: number
  session_mode: ThreadSessionMode
  active_faq_id: string | null
  active_faqs: unknown[]
  active_entity_type: string | null
  active_entity_id: string | null
  active_result_set_id: string | null
  active_result_set_type: string | null
  active_results: unknown[]
  active_filters: Record<string, unknown>
  last_turn_type: string | null
}

export interface ThreadMessage {
  id: string
  role: "user" | "assistant"
  content: string
  lang: string
  cards: CatalogCard[]
  created_at: string
}

export interface Thread {
  thread_id: string
  event_slug: string
  owner_type: string | null
  owner_id: string | null
  state: ThreadState
  messages: ThreadMessage[]
}

export interface ThreadSummary {
  thread_id: string
  event_slug: string
  event_year: number
  session_mode: ThreadSessionMode
  lang: string
  owner_type: string | null
  owner_id: string | null
  message_count: number
  last_message_preview: string
  created_at: string
  updated_at: string
}

export interface CreateThreadPayload {
  event_slug: string
  event_year: number
  lang?: string
  session_mode: ThreadSessionMode
  owner_type?: string
  owner_id?: string
}

export interface ThreadModeUpdatePayload {
  session_mode: ThreadSessionMode
  lang?: string
}

// SSE streaming types
export interface StreamStageData {
  name: string
  operation?: string
  route?: string
}

export interface StreamDeltaData {
  text: string
}

export interface StreamFinalData {
  thread_id: string
  message_id: string
  answer: string
  lang: string
  state: ThreadState
  plan: Record<string, unknown>
  cards: CatalogCard[]
  trace: Record<string, unknown>
}

// Compatibility types mirroring reference repo shape
export interface RecommendedQuestion {
  id: string
  question: string  // 백엔드로 전송되는 실제 질문 텍스트
  label?: string    // 버튼에 표시되는 짧은 레이블 (없으면 question 사용)
}

export interface StreamContext {
  name: string
  lang: "en" | "ko"
  company_name: string | null
  external_id: string
  image_url: string
  booth_number: string
  catalog_id: string
  type: "product" | "company"
}
