import type { LandingHub } from '@/domain/types'

export async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  const payload: unknown = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail =
      typeof (payload as { detail?: unknown })?.detail === 'string'
        ? (payload as { detail: string }).detail
        : '요청 실패'
    throw new Error(detail)
  }
  return payload as T
}

export type LandingPayload = {
  greeting: string
  hubs?: LandingHub[]
  visitor_primary_count?: number
  exhibitor_primary_count?: number
}

export async function fetchLanding(): Promise<LandingPayload> {
  return getJson('/tools/embedding/api/qa-quickmenu/landing')
}

export async function fetchPrimaryRows(qaUser: string): Promise<{ items: import('@/domain/types').QuickmenuItem[] }> {
  const q = new URLSearchParams({ qa_user: qaUser })
  return getJson(`/tools/embedding/api/qa-quickmenu/primary?${q}`)
}

export async function fetchFollowLinks(qnaCode: string): Promise<{ items: import('@/domain/types').QuickmenuItem[] }> {
  const u = `/tools/embedding/api/qa-quickmenu/${encodeURIComponent(qnaCode)}/follow-links?include_prompt=false`
  return getJson(u)
}

export async function fetchQuickmenuDetail(qnaCode: string): Promise<{ item: import('@/domain/types').QuickmenuItem }> {
  return getJson(`/tools/embedding/api/qa-quickmenu/${encodeURIComponent(qnaCode)}?include_prompt=true`)
}

export type SearchPayload = {
  answer?: string
  answer_korean?: string
  follow_up_questions?: { q?: string; label?: string; text?: string; ask?: string; qna_code?: string }[]
}

export async function postFaqSearch(
  query: string,
  faqUser: 'visitor' | 'exhibitor',
  sessionId: string | null,
): Promise<SearchPayload> {
  const fd = new FormData()
  fd.append('query', query)
  fd.append('model_id', 'Qwen/Qwen3-Embedding-0.6B')
  fd.append('device', 'cpu')
  fd.append('top_k', '8')
  fd.append('chunk_type', 'all')
  fd.append('answer_mode', 'template')
  fd.append('intent_use_openai', 'false')
  fd.append('faq_only', 'true')
  fd.append('faq_user', faqUser)
  if (sessionId) fd.append('session_id', sessionId)
  const res = await fetch('/tools/embedding/api/search', { method: 'POST', body: fd })
  const payload: unknown = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail =
      typeof (payload as { detail?: unknown })?.detail === 'string'
        ? (payload as { detail: string }).detail
        : 'FAQ 요청 실패'
    throw new Error(detail)
  }
  return payload as SearchPayload
}

export async function postChatQueue(message: string, sessionId: string): Promise<{ request_id: string }> {
  const fd = new FormData()
  fd.append('session_id', sessionId)
  fd.append('message', message)
  const res = await fetch('/chat', { method: 'POST', body: fd })
  const payload: unknown = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail =
      typeof (payload as { detail?: unknown })?.detail === 'string'
        ? (payload as { detail: string }).detail
        : '요청 실패'
    throw new Error(detail)
  }
  return payload as { request_id: string }
}

function parseSsePayloadData(raw: string | null): unknown {
  if (raw == null || raw === '') return raw
  try {
    return JSON.parse(raw) as unknown
  } catch {
    return raw
  }
}

export function takeNextDisplayChunk(s: string): string {
  if (!s) return ''
  if (/^\s/.test(s)) {
    const m = s.match(/^\s+/)
    return m ? m[0] : s[0]!
  }
  const m = s.match(/^[^\s]+/)
  return m ? m[0] : s[0]!
}

export function streamChatAnswer(
  requestId: string,
  opts: {
    onToken: (fullText: string) => void
    onCards: (cards: import('@/domain/types').SuggestionCard[]) => void
  },
): Promise<void> {
  return new Promise((resolve, reject) => {
    let fullText = ''
    let displayedLen = 0
    let drainTimer: ReturnType<typeof setInterval> | null = null
    let doneReceived = false
    let settled = false
    let botStarted = false

    const tryFinish = () => {
      if (!doneReceived) return
      if (displayedLen < fullText.length) return
      if (settled) return
      settled = true
      if (drainTimer) clearInterval(drainTimer)
      resolve()
    }

    const startDrain = () => {
      if (drainTimer) return
      drainTimer = setInterval(() => {
        const backlog = fullText.length - displayedLen
        const bursts = backlog > 200 ? 6 : backlog > 100 ? 4 : backlog > 40 ? 2 : 1
        for (let b = 0; b < bursts && displayedLen < fullText.length; b++) {
          const rest = fullText.slice(displayedLen)
          const chunk = takeNextDisplayChunk(rest)
          displayedLen += chunk.length
        }
        opts.onToken(fullText.slice(0, displayedLen))
        tryFinish()
      }, 18)
    }

    const applyTextChunk = (piece: unknown) => {
      const add = typeof piece === 'string' ? piece : String(piece ?? '')
      fullText += add
      botStarted = true
      startDrain()
    }

    const es = new EventSource(`/stream/${encodeURIComponent(requestId)}`)
    es.addEventListener('delta', (evt: MessageEvent) => {
      applyTextChunk(parseSsePayloadData(evt.data))
    })
    es.addEventListener('token', (evt: MessageEvent) => {
      applyTextChunk(parseSsePayloadData(evt.data))
    })
    es.addEventListener('final', (evt: MessageEvent) => {
      const raw = parseSsePayloadData(evt.data)
      const text = typeof raw === 'string' ? raw : String(raw ?? '')
      if (text) {
        fullText = text
        botStarted = true
        startDrain()
      }
    })
    const applyCards = (evt: MessageEvent) => {
      const cards = parseSsePayloadData(evt.data)
      if (Array.isArray(cards) && cards.length) {
        opts.onCards(cards as import('@/domain/types').SuggestionCard[])
        botStarted = true
      }
    }
    es.addEventListener('citation', applyCards)
    es.addEventListener('cards', applyCards)
    es.addEventListener('done', () => {
      doneReceived = true
      es.close()
      if (!fullText && !botStarted) {
        if (!settled) {
          settled = true
          if (drainTimer) clearInterval(drainTimer)
          resolve()
        }
        return
      }
      if (fullText.length > displayedLen) startDrain()
      else tryFinish()
    })
    es.addEventListener('error', (evt: MessageEvent) => {
      es.close()
      const d = parseSsePayloadData(evt.data)
      if (!settled) {
        settled = true
        if (drainTimer) clearInterval(drainTimer)
        reject(new Error(typeof d === 'string' ? d : '스트림 오류'))
      }
    })
    es.onerror = () => {
      if (settled || doneReceived) return
      es.close()
      if (!settled) {
        settled = true
        if (drainTimer) clearInterval(drainTimer)
        reject(new Error('SSE 연결이 종료되었습니다.'))
      }
    }
  })
}
