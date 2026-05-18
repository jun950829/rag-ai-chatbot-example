import type { LandingHub } from '@/domain/types'

/** 같은 오리진이 아닐 때(예: 로컬 Vite만 띄우고 API는 다른 포트) `VITE_API_BASE` 설정 */
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''

function apiUrl(path: string): string {
  if (!path.startsWith('/')) return `${API_BASE}/${path}`
  return `${API_BASE}${path}`
}

export async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(apiUrl(url))
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
  const res = await fetch(apiUrl('/tools/embedding/api/search'), { method: 'POST', body: fd })
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

type SseFrame = { event: string; data: string }

function extractSseFrames(buf: string): { frames: SseFrame[]; rest: string } {
  const frames: SseFrame[] = []
  let rest = buf
  while (true) {
    const idx = rest.indexOf('\n\n')
    if (idx < 0) break
    const block = rest.slice(0, idx)
    rest = rest.slice(idx + 2)
    const lines = block.split('\n')
    let event = 'message'
    const dataLines: string[] = []
    for (const ln of lines) {
      if (ln.startsWith('event:')) event = ln.slice('event:'.length).trim() || event
      if (ln.startsWith('data:')) dataLines.push(ln.slice('data:'.length).trimStart())
    }
    frames.push({ event, data: dataLines.join('\n') })
  }
  return { frames, rest }
}

export function streamChatAnswer(
  message: string,
  sessionId: string,
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

    const applyCards = (rawData: string) => {
      const cards = parseSsePayloadData(rawData)
      if (Array.isArray(cards) && cards.length) {
        opts.onCards(cards as import('@/domain/types').SuggestionCard[])
        botStarted = true
      }
    }

    const fd = new FormData()
    fd.append('session_id', sessionId)
    fd.append('message', message)

    fetch(apiUrl('/chat'), { method: 'POST', body: fd })
      .then(async (res) => {
        if (!res.ok) {
          const payload: unknown = await res.json().catch(() => ({}))
          const detail =
            typeof (payload as { detail?: unknown })?.detail === 'string'
              ? (payload as { detail: string }).detail
              : '요청 실패'
          throw new Error(detail)
        }
        if (!res.body) throw new Error('스트림 응답이 없습니다.')

        const reader = res.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buf = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const parsed = extractSseFrames(buf)
          buf = parsed.rest
          for (const f of parsed.frames) {
            if (f.event === 'delta' || f.event === 'token') applyTextChunk(parseSsePayloadData(f.data))
            else if (f.event === 'final') {
              const raw = parseSsePayloadData(f.data)
              const text = typeof raw === 'string' ? raw : String(raw ?? '')
              if (text) {
                fullText = text
                botStarted = true
                startDrain()
              }
            } else if (f.event === 'citation' || f.event === 'cards') applyCards(f.data)
            else if (f.event === 'done') doneReceived = true
            else if (f.event === 'error') {
              const d = parseSsePayloadData(f.data)
              throw new Error(typeof d === 'string' ? d : '스트림 오류')
            }
          }
        }

        doneReceived = true
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
      .catch((e) => {
        if (!settled) {
          settled = true
          if (drainTimer) clearInterval(drainTimer)
          reject(e instanceof Error ? e : new Error(String(e)))
        }
      })
  })
}

/** 카드 ``external_id`` 로 DB 조회 후 LLM만 스트리밍 (새 RAG 검색 없음). */
export function streamCardDetail(
  sessionId: string,
  externalId: string,
  entityKind: string | undefined,
  opts: { onToken: (fullText: string) => void; language?: string },
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

    const fd = new FormData()
    fd.append('session_id', sessionId)
    fd.append('external_id', externalId)
    if (entityKind) fd.append('entity_kind', entityKind)
    if (opts.language) fd.append('language', opts.language)

    fetch(apiUrl('/chat/card-detail'), { method: 'POST', body: fd })
      .then(async (res) => {
        if (!res.ok) {
          const payload: unknown = await res.json().catch(() => ({}))
          const detail =
            typeof (payload as { detail?: unknown })?.detail === 'string'
              ? (payload as { detail: string }).detail
              : '요청 실패'
          throw new Error(detail)
        }
        if (!res.body) throw new Error('스트림 응답이 없습니다.')

        const reader = res.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buf = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const parsed = extractSseFrames(buf)
          buf = parsed.rest
          for (const f of parsed.frames) {
            if (f.event === 'delta' || f.event === 'token') applyTextChunk(parseSsePayloadData(f.data))
            else if (f.event === 'final') {
              const raw = parseSsePayloadData(f.data)
              const text = typeof raw === 'string' ? raw : String(raw ?? '')
              if (text) {
                fullText = text
                botStarted = true
                startDrain()
              }
            } else if (f.event === 'done') doneReceived = true
            else if (f.event === 'error') {
              const d = parseSsePayloadData(f.data)
              throw new Error(typeof d === 'string' ? d : '스트림 오류')
            }
          }
        }

        doneReceived = true
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
      .catch((e) => {
        if (!settled) {
          settled = true
          if (drainTimer) clearInterval(drainTimer)
          reject(e instanceof Error ? e : new Error(String(e)))
        }
      })
  })
}
