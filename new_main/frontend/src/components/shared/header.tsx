"use client"

import { CloseIcon } from "@/components/icons"
import { emitCloseClicked } from "@/constants/event-contracts"
import { resetChatToHome } from "@/stores/chat.store"

const Header: React.FC = () => (
  <header className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
    <div className="w-8 shrink-0" />
    <h1 className="text-sm font-semibold text-gray-800">Exmatch AI</h1>
    <button
      type="button"
      className="rounded p-1 hover:bg-gray-100"
      onClick={() => {
        resetChatToHome()
        emitCloseClicked()
      }}
      aria-label="Close"
    >
      <CloseIcon className="size-5 text-gray-600" />
    </button>
  </header>
)

export { Header }
