export type HubMode = 'visitor_faq' | 'exhibitor_faq' | 'company_rag'

export type QuickmenuItem = {
  qna_code: string
  primary_question?: boolean | null
  quickmenu_display_label?: string | null
  quickmenu_label?: string | null
  category?: string | null
  subcategory?: string | null
  domain?: string | null
  question_sample?: string | null
  answer_sample?: string | null
  /** 레거시/별칭 필드 */
  answer_question?: string | null
  links?: string | null
  follow_questions_resolved?: FollowResolved[]
}

export type FollowResolved = {
  code?: string
  resolved_qna_code?: string | null
  item?: QuickmenuItem | null
}

export type LandingHub = {
  id: string
  title: string
  subtitle?: string
  kind: string
  qa_user?: string
  seed_qna_code?: string
}

export type SuggestionCard = {
  title?: string
  subtitle?: string
  image_url?: string
  entity_kind?: string
  follow_prompt?: string
  external_id?: string | null
}

export type ChatMessage = {
  id: string
  role: 'user' | 'bot'
  text: string
  cards?: SuggestionCard[]
  followups?: { label: string; qnaCode: string }[]
  typing?: boolean
}
