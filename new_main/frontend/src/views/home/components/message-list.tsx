import { FC, Fragment } from "react"
import { CatalogCardList } from "@/components/shared/catalog-card-list"
import { ChatQuestion } from "@/components/shared/chat-question"
import { ChatResponse } from "@/components/shared/chat-response"
import SuggestedQuestion from "@/components/shared/suggested-question"
import type { SessionMode } from "@/hooks/chat"
import { MotionDiv } from "@/lib/motion"
import { Message } from "@/stores/chat.store"
import type { CatalogCard } from "@/types/chat.types"

import { ModeSelector } from "./mode-selector"

interface MessageListProps {
  messages: Message[]
  onSendQuestion: (question: string) => void
  onCardDetail?: (card: CatalogCard) => void
  onSelectMode: (mode: SessionMode) => void
  currentMode: SessionMode
}

const MessageList: FC<MessageListProps> = ({
  messages,
  onSendQuestion,
  onCardDetail,
  onSelectMode,
  currentMode,
}) => (
  <Fragment>
    {messages.map((message, index) => {
      const isLast = index === messages.length - 1
      if (message.type === "question") {
        return (
          <li key={message.id} className="w-full list-none">
            <MotionDiv
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
            >
              <ChatQuestion content={message.content} />
            </MotionDiv>
          </li>
        )
      }

      return (
        <li key={message.id} className="w-full list-none">
          <MotionDiv
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
          >
            <ChatResponse content={message.content} isFirstMessage={index === 0} feedback={message.feedback}>
              {message.cards && message.cards.length > 0 && (
                <CatalogCardList cards={message.cards.slice(0, 5)} onDetail={onCardDetail} />
              )}
              {message.recommended_questions && message.recommended_questions.length > 0 && (
                <div className="flex w-full flex-col gap-2">
                  {message.recommended_questions.map((q) => (
                    <SuggestedQuestion
                      key={q.id}
                      question={q.question}
                      label={q.label}
                      isSelected={message.selected_recommended_question_id === q.id}
                      onClick={() => onSendQuestion(q.question)}
                    />
                  ))}
                </div>
              )}
            </ChatResponse>
            {message.show_catalog_mode_switcher === true && isLast && (
              <div className="mt-2 max-w-[min(100%,32rem)] pl-1">
                <ModeSelector onSelectMode={onSelectMode} currentMode={currentMode} />
              </div>
            )}
          </MotionDiv>
        </li>
      )
    })}
  </Fragment>
)

export { MessageList }
