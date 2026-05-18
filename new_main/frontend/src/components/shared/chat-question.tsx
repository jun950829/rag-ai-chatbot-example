import { FC } from "react"

const ChatQuestion: FC<{ content: string }> = ({ content }) => (
  <div className="flex w-full justify-end">
    <p className="max-w-[min(100%,85%)] rounded-[16px_16px_2px_16px] border border-red-400/25 bg-red-500 px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm">
      {content}
    </p>
  </div>
)

export { ChatQuestion }
