import { FC } from "react"
import { Button } from "@/components/ui/button"

interface SuggestedQuestionProps {
  question: string
  label?: string
  isSelected: boolean
  onClick: () => void
}

const SuggestedQuestion: FC<SuggestedQuestionProps> = ({ question, label, isSelected, onClick }) => (
  <Button
    role="button"
    tabIndex={0}
    onClick={onClick}
    data-selected={isSelected}
    className="h-fit min-h-10 w-full items-start justify-start bg-white text-start shadow-sm"
  >
    <span className="mr-1 font-semibold text-navy-500">Q.</span>
    <span>{label ?? question}</span>
  </Button>
)

export default SuggestedQuestion
