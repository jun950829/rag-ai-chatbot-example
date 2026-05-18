import React, { Fragment } from "react"
import { BotIcon, DisLikeFilledIcon, DisLikeIcon, LikeFilledIcon, LikeIcon } from "@/components/icons"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { ClipboardCopy } from "./clipboard-copy"
import { Loading } from "./loading"
import { RichContent } from "./rich-content"

type ChatResponseProps = {
  content: string | null
  isStreaming?: boolean
  stageMessage?: string | null
  isFirstMessage?: boolean
  feedback?: "like" | "dislike" | null
  onToggleLike?: () => Promise<void>
  onToggleDisLike?: () => Promise<void>
  children?: React.ReactNode
}

const ChatResponse: React.FC<ChatResponseProps> = ({
  content,
  isStreaming = false,
  stageMessage,
  isFirstMessage = false,
  feedback,
  onToggleLike,
  onToggleDisLike,
  children,
}) => {
  const hasText = Boolean((content || "").trim())
  const hasChildren = Boolean(children)
  const showBubble = hasText || isStreaming || hasChildren

  return (
    <div
      className={cn("flex w-full flex-col gap-1.5", isFirstMessage && "pt-1")}
    >
      <div className="flex max-w-[min(100%,32rem)] items-center gap-2">
        <BotIcon className="size-8 shrink-0 text-gray-600" />
        <span className="text-xs font-medium text-gray-500">AI Assistant</span>
      </div>

      {showBubble && (
        <div
          className={cn(
            "max-w-[min(100%,32rem)] rounded-[2px_18px_18px_18px] border border-gray-200/90",
            "bg-white px-4 py-3 text-gray-900 shadow-sm"
          )}
        >
          {hasText && <RichContent content={content!} className="mt-0" />}

          {isStreaming && (
            <div className={cn(hasText && "mt-2")}>
              {!hasText && stageMessage && <p className="mb-2 text-sm text-gray-500">{stageMessage}</p>}
              <Loading />
            </div>
          )}

          {hasChildren && <div className={cn(hasText || isStreaming ? "mt-3 border-t border-gray-200/80 pt-3" : "")}>{children}</div>}
        </div>
      )}

      {!showBubble && children}

      {!isStreaming && hasText && !isFirstMessage && (
        <div className="mt-1.5 flex max-w-[min(100%,32rem)] items-center gap-2 pl-1">
          {onToggleLike && onToggleDisLike && (
            <Fragment>
              <Button variant="icon" type="button" onClick={() => void onToggleLike()}>
                {feedback === "like" ? <LikeFilledIcon className="size-5" /> : <LikeIcon className="size-5" />}
              </Button>
              <Button variant="icon" type="button" onClick={() => void onToggleDisLike()}>
                {feedback === "dislike" ? <DisLikeFilledIcon className="size-5" /> : <DisLikeIcon className="size-5" />}
              </Button>
            </Fragment>
          )}
          <ClipboardCopy text={content!} />
        </div>
      )}
    </div>
  )
}

export { ChatResponse }
