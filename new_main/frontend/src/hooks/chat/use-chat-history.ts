import { useQuery } from "@tanstack/react-query"

import { QueryKeys } from "@/constants/query-keys"
import { chatService } from "@/services/chat.service"

export function useChatHistory(threadId: string | null) {
  return useQuery({
    queryKey: [...QueryKeys.chat.history, threadId],
    queryFn: () => chatService.loadThread(threadId!),
    enabled: !!threadId,
  })
}
