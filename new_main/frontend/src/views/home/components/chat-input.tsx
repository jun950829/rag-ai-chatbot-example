import { FC } from "react"
import { SendIcon } from "@/components/icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

interface ChatInputProps {
  value: string
  disabled: boolean
  onChange: (value: string) => void
  onSubmit: () => void
  placeholder?: string
}

const ChatInput: FC<ChatInputProps> = ({ value, disabled, onChange, onSubmit, placeholder = "무엇이든 물어보세요." }) => {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit()
  }

  return (
    <section className="absolute bottom-0 z-10 flex w-full flex-col gap-1 bg-white px-4 pb-2 pt-3">
      <form className="flex items-center gap-1.5" onSubmit={handleSubmit}>
        <Input
          placeholder={placeholder}
          className="w-full"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              onSubmit()
            }
          }}
        />
        <Button variant="send" type="submit" disabled={disabled || !value.trim()} className="size-10 shrink-0">
          <SendIcon className="size-5" />
        </Button>
      </form>
      <span className="text-center text-[10px] text-gray-300">Powered by Exmatch AI</span>
    </section>
  )
}

export { ChatInput }
