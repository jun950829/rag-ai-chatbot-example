import { create } from 'zustand'

import type { HubMode } from '@/domain/types'

type ChatStore = {
  hubMode: HubMode
  conversationStarted: boolean
  sessionId: string
  setHubMode: (m: HubMode) => void
  startConversation: () => void
}

export const useChatStore = create<ChatStore>((set) => ({
  hubMode: 'visitor_faq',
  conversationStarted: false,
  sessionId: `web-${Math.random().toString(36).slice(2, 10)}`,
  setHubMode: (m) => set({ hubMode: m }),
  startConversation: () => set({ conversationStarted: true }),
}))
