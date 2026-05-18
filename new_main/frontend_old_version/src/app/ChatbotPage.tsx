import { useQuery } from '@tanstack/react-query'
import type { FormEvent } from 'react'
import { useCallback, useMemo, useRef, useState } from 'react'

import {
  fetchFollowLinks,
  fetchLanding,
  fetchPrimaryRows,
  fetchQuickmenuDetail,
  postFaqSearch,
  streamCardDetail,
  streamChatAnswer,
} from '@/api/client'
import { HeadsetHero } from '@/app/hero/HeadsetHero'
import { useChatStore } from '@/app/store'
import { quickmenuDisplayLabel } from '@/domain/quickmenu'
import type { ChatMessage, HubMode, LandingHub, QuickmenuItem, SuggestionCard } from '@/domain/types'
import { ModeSelect } from '@/ui/ModeSelect'
import { QuickMenuGrid } from '@/ui/QuickMenuGrid'
import { SuggestionCarousel } from '@/ui/SuggestionCarousel'

function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms))
}

function addFaqAnswerMessage(item: QuickmenuItem): string {
  const answerText = (item.answer_sample || item.answer_question || '저장된 답변이 없습니다.').trim()
  const linkText = (item.links || '').trim()
  return `A. ${answerText}${linkText ? `\n링크: ${linkText}` : ''}`
}

async function streamFaqBlocks(full: string, onUpdate: (s: string) => void) {
  const tokens = full.split(/(\s+)/)
  let acc = ''
  for (const tk of tokens) {
    acc += tk
    onUpdate(acc)
    await sleep(16 + Math.floor(Math.random() * 18))
  }
}

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function detectLang(text: string): 'ko' | 'en' {
  const hangul = (text.match(/[\uac00-\ud7a3]/g) || []).length
  const english = (text.match(/[A-Za-z]/g) || []).length
  const total = hangul + english
  if (total === 0) return 'ko'
  return english / total >= 0.7 ? 'en' : 'ko'
}

function ragSeedFromLanding(hubs: LandingHub[] | undefined): string {
  const hub = hubs?.find((h) => h.kind === 'rag' || h.id === 'company_product_rag')
  const code = String(hub?.seed_qna_code || '').trim()
  return code || 'kp_vis_showinfo_003'
}

export function ChatbotPage() {
  const { hubMode, setHubMode, conversationStarted, startConversation, sessionId } = useChatStore()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [statusLine, setStatusLine] = useState('준비됨')
  const [statusError, setStatusError] = useState(false)
  const [busy, setBusy] = useState(false)
  const [landingDraft, setLandingDraft] = useState('')
  const logRef = useRef<HTMLDivElement>(null)

  const { data: landing } = useQuery({
    queryKey: ['landing'],
    queryFn: fetchLanding,
  })

  const seedCode = ragSeedFromLanding(landing?.hubs)

  const primaryVisitor = useQuery({
    queryKey: ['qa-primary', 'visitor'],
    queryFn: () => fetchPrimaryRows('visitor').then((r) => r.items),
    enabled: hubMode === 'visitor_faq',
  })
  const primaryExhibitor = useQuery({
    queryKey: ['qa-primary', 'exhibitor'],
    queryFn: () => fetchPrimaryRows('exhibitor').then((r) => r.items),
    enabled: hubMode === 'exhibitor_faq',
  })
  const ragQuick = useQuery({
    queryKey: ['rag-quick', seedCode],
    queryFn: () => fetchFollowLinks(seedCode).then((r) => r.items),
    enabled: hubMode === 'company_rag',
  })

  const landingGridItems = useMemo(() => {
    if (!conversationStarted) {
      if (hubMode === 'visitor_faq') return primaryVisitor.data ?? []
      if (hubMode === 'exhibitor_faq') return primaryExhibitor.data ?? []
      return ragQuick.data ?? []
    }
    return []
  }, [
    conversationStarted,
    hubMode,
    primaryVisitor.data,
    primaryExhibitor.data,
    ragQuick.data,
  ])

  const chipItems = useMemo(() => {
    if (!conversationStarted) return []
    if (hubMode === 'visitor_faq') return primaryVisitor.data ?? []
    if (hubMode === 'exhibitor_faq') return primaryExhibitor.data ?? []
    return []
  }, [conversationStarted, hubMode, primaryVisitor.data, primaryExhibitor.data])

  const scrollToBottom = () => {
    queueMicrotask(() => {
      const el = logRef.current
      if (el) el.scrollTop = el.scrollHeight
    })
  }

  const appendMessage = useCallback((m: ChatMessage) => {
    setMessages((xs) => [...xs, m])
    scrollToBottom()
  }, [])

  const updateLastBot = useCallback((partial: Partial<ChatMessage>) => {
    setMessages((xs) => {
      const next = [...xs]
      let idx = -1
      for (let k = next.length - 1; k >= 0; k--) {
        if (next[k]?.role === 'bot') {
          idx = k
          break
        }
      }
      if (idx >= 0) next[idx] = { ...next[idx]!, ...partial }
      return next
    })
    scrollToBottom()
  }, [])

  const resolveFollowItems = async (item: QuickmenuItem, qnaCode: string): Promise<{ qna_code: string; label: string }[]> => {
    const resolved = Array.isArray(item.follow_questions_resolved) ? item.follow_questions_resolved : []
    if (resolved.length) {
      return resolved
        .map((r) => {
          const code = String(r.resolved_qna_code || r.code || '').trim()
          const it = r.item
          const label = it ? quickmenuDisplayLabel(it) : ''
          return {
            qna_code: code,
            label: label || code,
          }
        })
        .filter((x) => x.qna_code)
    }
    const next = await fetchFollowLinks(qnaCode)
    return (next.items || []).map((it) => ({
      qna_code: it.qna_code,
      label: quickmenuDisplayLabel(it) || it.qna_code,
    }))
  }

  const faqUser = (): 'visitor' | 'exhibitor' =>
    hubMode === 'exhibitor_faq' ? 'exhibitor' : 'visitor'

  const handleStoredAnswer = async (qnaCode: string) => {
    if (busy) return
    if (!conversationStarted) startConversation()
    setBusy(true)
    setStatusError(false)
    setStatusLine('저장 FAQ 조회 중...')
    try {
      const detail = await fetchQuickmenuDetail(qnaCode)
      const item = detail.item || {}
      const qText = String(item.question_sample || quickmenuDisplayLabel(item) || qnaCode).trim()
      if (qText) appendMessage({ id: newId(), role: 'user', text: qText })

      const follow = await resolveFollowItems(item, qnaCode)

      const botId = newId()
      appendMessage({ id: botId, role: 'bot', text: '', typing: true })
      await sleep(400)
      setStatusLine('응답 생성 중...')
      const finalText = addFaqAnswerMessage(item)

      await streamFaqBlocks(finalText, (t) => updateLastBot({ text: t, typing: false }))

      updateLastBot({
        typing: false,
        followups: follow.map((n) => ({ label: n.label, qnaCode: n.qna_code })),
      })
      setStatusLine('완료')
    } catch (e) {
      setStatusError(true)
      setStatusLine('오류')
      appendMessage({ id: newId(), role: 'bot', text: `저장 FAQ 조회 실패: ${e instanceof Error ? e.message : String(e)}` })
    } finally {
      setBusy(false)
      scrollToBottom()
    }
  }

  const runFaqFreeText = async (text: string) => {
    setStatusLine('FAQ 답변을 찾는 중...')
    const botId = newId()
    appendMessage({ id: botId, role: 'bot', text: '', typing: true })
    try {
      const payload = await postFaqSearch(text.trim(), faqUser(), sessionId)
      const ans =
        String(payload.answer || payload.answer_korean || '').trim() || '등록된 FAQ 답변을 찾지 못했습니다.'
      updateLastBot({
        typing: false,
        text: ans,
        cards: undefined,
      })
      const raw = payload.follow_up_questions || []
      const followups = raw
        .map((f) => ({
          qna_code: String(f.qna_code || '').trim(),
          label: String(f.label || f.ask || f.q || '').trim(),
        }))
        .filter((f) => f.qna_code && f.label)
        .map((f) => ({ qnaCode: f.qna_code, label: f.label }))
      if (followups.length) updateLastBot({ followups })
      setStatusLine('완료')
    } catch (e) {
      updateLastBot({ typing: false, text: `오류: ${e instanceof Error ? e.message : String(e)}` })
      setStatusError(true)
      setStatusLine('오류가 발생했습니다.')
    }
  }

  const runRagPipelineFixed = async (text: string) => {
    setStatusLine('응답을 생성하는 중...')
    const botId = newId()
    appendMessage({ id: botId, role: 'bot', text: '', typing: true, cards: undefined })
    let accumulated = ''
    let cardsAccumulator: SuggestionCard[] | undefined
    try {
      await streamChatAnswer(text.trim(), sessionId, {
        onToken: (displayed) => {
          accumulated = displayed
          updateLastBot({
            typing: false,
            text: displayed,
            cards: cardsAccumulator,
          })
        },
        onCards: (c) => {
          cardsAccumulator = c
          updateLastBot({ cards: c, typing: false, text: accumulated })
        },
      })
      updateLastBot({
        typing: false,
        text: accumulated || (cardsAccumulator?.length ? '' : '응답이 없습니다.'),
        cards: cardsAccumulator,
      })
      setStatusLine('완료')
    } catch (e) {
      updateLastBot({
        typing: false,
        text: `오류: ${e instanceof Error ? e.message : String(e)}`,
        cards: cardsAccumulator,
      })
      setStatusError(true)
      setStatusLine('오류가 발생했습니다.')
    }
  }

  const handleSubmitComposer = async (raw: string) => {
    const text = raw.trim()
    if (!text || busy) return
    setBusy(true)
    setStatusError(false)
    if (!conversationStarted) startConversation()

    appendMessage({ id: newId(), role: 'user', text })

    try {
      if (hubMode === 'visitor_faq' || hubMode === 'exhibitor_faq') await runFaqFreeText(text)
      else await runRagPipelineFixed(text)
    } finally {
      setBusy(false)
      scrollToBottom()
    }
  }

  const onLandingSubmit = (e?: FormEvent) => {
    e?.preventDefault()
    const t = landingDraft.trim()
    if (!t || busy) return
    setLandingDraft('')
    void handleSubmitComposer(t)
  }

  const lastUserLang = useCallback((): 'ko' | 'en' => {
    for (let k = messages.length - 1; k >= 0; k--) {
      if (messages[k]?.role === 'user') return detectLang(messages[k]!.text)
    }
    return 'ko'
  }, [messages])

  const onCarouselDetail = async (card: SuggestionCard) => {
    const ext = String(card.external_id || '').trim()
    const title = String(card.title || '').trim()
    if (busy) return

    if (hubMode === 'company_rag' && ext) {
      if (!conversationStarted) startConversation()
      setBusy(true)
      setStatusError(false)
      const lang = lastUserLang()
      setStatusLine(lang === 'en' ? 'Loading card detail...' : '카드 상세를 불러오는 중...')
      appendMessage({ id: newId(), role: 'user', text: title ? `상세 · ${title}` : `상세 · ${ext}` })
      const botId = newId()
      appendMessage({ id: botId, role: 'bot', text: '', typing: true, cards: undefined })
      let accumulated = ''
      try {
        await streamCardDetail(sessionId, ext, card.entity_kind, {
          onToken: (displayed) => {
            accumulated = displayed
            updateLastBot({ typing: false, text: displayed, cards: undefined })
          },
          language: lang,
        })
        updateLastBot({
          typing: false,
          text: accumulated || '응답이 없습니다.',
          cards: undefined,
        })
        setStatusLine('완료')
      } catch (e) {
        updateLastBot({
          typing: false,
          text: `오류: ${e instanceof Error ? e.message : String(e)}`,
        })
        setStatusError(true)
        setStatusLine('오류가 발생했습니다.')
      } finally {
        setBusy(false)
        scrollToBottom()
      }
      return
    }

    const follow =
      String(card.follow_prompt || '').trim() ||
      `${String(card.title || '').trim()}에 대해 자세히 알려줘`
    void handleSubmitComposer(follow)
  }

  const greeting = landing?.greeting?.trim()

  const shellWidth = 'max-w-[480px]'

  return (
    <div className="relative flex min-h-full flex-col">
      {/* shell background */}
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_#ffffff_0%,_#f5f7fb_55%)]" />

      {!conversationStarted ? (
        <div className={`mx-auto flex w-full ${shellWidth} flex-col items-center gap-8 px-4 py-10 pb-28`}>
          <HeadsetHero />
          <div className="space-y-1 text-center">
            <h1 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">Test_AI 챗봇</h1>
            <p className="text-sm font-semibold leading-relaxed text-slate-900 sm:text-base">{greeting || '무엇을 도와드릴까요?'}</p>
            {landing?.visitor_primary_count != null ? (
              <p className="text-xs text-slate-500">참관객 카테고리 {landing.visitor_primary_count} · 참가업체 카테고리 {landing.exhibitor_primary_count}</p>
            ) : null}
          </div>

          <ModeSelect value={hubMode} onChange={(m: HubMode) => setHubMode(m)} />

          <form onSubmit={onLandingSubmit} className={`w-full ${shellWidth}`}>
            <div className="relative">
              <input
                value={landingDraft}
                onChange={(e) => setLandingDraft(e.target.value)}
                placeholder="궁금한 점을 검색해 보세요"
                disabled={busy}
                className="w-full rounded-full border border-slate-200 bg-white px-5 py-3.5 pr-12 text-sm text-slate-900 shadow-sm outline-none ring-slate-300 placeholder:text-slate-400 focus:ring-2 disabled:opacity-60"
                aria-label="검색어"
              />
              <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-lg text-slate-500">⌕</span>
            </div>
            <p className="mt-2 px-2 text-xs text-slate-500">입력 후 Enter 로 검색합니다.</p>
          </form>

          <div className={`w-full ${shellWidth} space-y-3`}>
            {hubMode !== 'company_rag' ? (
              <p className="text-center text-xs font-medium uppercase tracking-wide text-slate-500">바로 묻기</p>
            ) : (
              <p className="text-center text-xs text-slate-500">실무 예시부터 골라보거나 검색창으로 질문해 주세요.</p>
            )}
            <QuickMenuGrid
              items={landingGridItems}
              onPick={(it) => {
                handleStoredAnswer(it.qna_code).catch(console.error)
              }}
            />
            {hubMode === 'visitor_faq' && primaryVisitor.isLoading ? (
              <p className="text-center text-sm text-slate-500">퀵 메뉴 불러오는 중…</p>
            ) : null}
            {hubMode === 'exhibitor_faq' && primaryExhibitor.isLoading ? (
              <p className="text-center text-sm text-slate-500">퀵 메뉴 불러오는 중…</p>
            ) : null}
            {hubMode === 'company_rag' && ragQuick.isLoading ? (
              <p className="text-center text-sm text-slate-500">추천 주제 불러오는 중…</p>
            ) : null}
          </div>
        </div>
      ) : (
        <>
          <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur">
            <div className={`mx-auto flex ${shellWidth} flex-col gap-2`}>
              <ModeSelect value={hubMode} onChange={(m: HubMode) => setHubMode(m)} compact />
              <div className="min-h-[2.5rem]">
                {hubMode === 'company_rag' ? (
                  <p className="text-center text-xs text-slate-500">저장 정보·검색으로 참가기업·전시품을 안내합니다. 아래 채팅으로 질문해 주세요.</p>
                ) : (
                  <div className="flex flex-wrap justify-center gap-2">
                    {chipItems.map((item) => (
                      <button
                        key={item.qna_code}
                        type="button"
                        onClick={() => handleStoredAnswer(item.qna_code).catch(console.error)}
                        className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-800 hover:border-slate-300 hover:bg-slate-50"
                      >
                        {quickmenuDisplayLabel(item)}
                      </button>
                    ))}
                    {hubMode === 'visitor_faq' && primaryVisitor.isFetching ? (
                      <span className="text-xs text-slate-400">로드 중…</span>
                    ) : null}
                    {hubMode === 'exhibitor_faq' && primaryExhibitor.isFetching ? (
                      <span className="text-xs text-slate-400">로드 중…</span>
                    ) : null}
                  </div>
                )}
              </div>
            </div>
          </header>

          <main
            ref={logRef}
            className={`mx-auto flex w-full ${shellWidth} flex-1 flex-col gap-3 overflow-y-auto px-4 py-4`}
            style={{ maxHeight: 'calc(100vh - 210px)' }}
          >
            {messages.map((m) => (
              <div
                key={m.id}
                className={`flex flex-col gap-3 ${m.role === 'user' ? 'items-end' : 'items-start'}`}
              >
                <div
                  className={
                    m.role === 'user'
                      ? 'max-w-[78%] rounded-xl bg-slate-900 px-3 py-2.5 text-sm leading-relaxed text-white'
                      : 'max-w-[92%] rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm leading-relaxed text-slate-900 shadow-sm'
                  }
                >
                  {m.role === 'bot' && m.typing ? (
                    <span className="text-slate-500">답변 준비 중…</span>
                  ) : (
                    <div className="whitespace-pre-wrap break-words">{m.text}</div>
                  )}
                  {m.cards?.length ? <SuggestionCarousel cards={m.cards} onDetail={onCarouselDetail} /> : null}
                  {m.followups?.length ? (
                    <div className="mt-2 flex flex-wrap gap-1.5 border-t border-slate-100 pt-2">
                      {m.followups.map((fu) => (
                        <button
                          key={fu.qnaCode}
                          type="button"
                          onClick={() => handleStoredAnswer(fu.qnaCode).catch(console.error)}
                          className="rounded-full border border-slate-300 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-900 hover:bg-slate-100"
                        >
                          {fu.label}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </main>

          <footer className="sticky bottom-0 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
            <div className={`mx-auto flex ${shellWidth} gap-2`}>
              <ComposerLocked onSend={handleSubmitComposer} disabled={busy} />
            </div>
            <p className={`mx-auto mt-1 ${shellWidth} px-1 text-xs ${statusError ? 'text-red-600' : 'text-slate-500'}`}>{statusLine}</p>
          </footer>
        </>
      )}
    </div>
  )
}

function ComposerLocked({ onSend, disabled }: { onSend: (t: string) => void; disabled: boolean }) {
  const [v, setV] = useState('')
  const send = () => {
    if (!v.trim() || disabled) return
    onSend(v)
    setV('')
  }
  return (
    <>
      <textarea
        value={v}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            send()
          }
        }}
        placeholder="메시지를 입력하세요"
        rows={2}
        disabled={disabled}
        className="min-h-[50px] flex-1 resize-y rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none ring-slate-400 focus:border-slate-900 focus:ring-1 disabled:opacity-60"
      />
      <button
        type="button"
        onClick={send}
        disabled={disabled || !v.trim()}
        className="rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white disabled:opacity-50"
      >
        전송
      </button>
    </>
  )
}
