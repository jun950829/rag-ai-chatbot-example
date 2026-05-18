import { FC } from "react"
import { Button } from "@/components/ui/button"
import { SessionMode } from "@/hooks/chat"

interface ModeSelectorProps {
  onSelectMode: (mode: SessionMode) => void
  currentMode?: SessionMode
}

const MODES: { value: SessionMode; label: string }[] = [
  { value: "faq_visitor", label: "참관객 FAQ" },
  { value: "faq_exhibitor", label: "참가업체 FAQ" },
  { value: "catalog", label: "제품/기업 검색" },
]

const ModeSelector: FC<ModeSelectorProps> = ({ onSelectMode, currentMode }) => (
  <div className="mt-3 flex flex-wrap items-center gap-2">
    {MODES.map(({ value, label }) => (
      <Button
        key={value}
        variant="chip"
        className="whitespace-nowrap"
        onClick={() => onSelectMode(value)}
        data-selected={currentMode === value}
      >
        {label}
      </Button>
    ))}
  </div>
)

export { ModeSelector }
