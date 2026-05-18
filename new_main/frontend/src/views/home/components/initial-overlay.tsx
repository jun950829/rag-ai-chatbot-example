import { FC } from "react"
import { BotIcon } from "@/components/icons"
import { Button } from "@/components/ui/button"
import { SessionMode } from "@/hooks/chat"
import { MotionDiv } from "@/lib/motion"

interface IntroOverlayProps {
  onSelectMode: (mode: SessionMode) => void
}

export const IntroOverlay: FC<IntroOverlayProps> = ({ onSelectMode }) => (
  <MotionDiv
    className="absolute inset-0 z-30 flex flex-col bg-white"
    initial={{ opacity: 0.5 }}
    animate={{ opacity: 1 }}
    exit={{ opacity: 0, transition: { duration: 0.28, ease: "easeInOut" } }}
  >
    <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
      <div className="w-8" />
      <h1 className="text-sm font-semibold text-gray-800">Exmatch AI</h1>
      <div className="w-8" />
    </div>

    <MotionDiv
      className="flex w-full flex-1 flex-col items-center px-6 pt-12 text-center"
      initial={{ y: 24, opacity: 0 }}
      animate={{ y: 0, opacity: 1, transition: { duration: 0.36, ease: "easeOut", delay: 0.06 } }}
      exit={{ y: -18, opacity: 0, transition: { duration: 0.22, ease: "easeInOut" } }}
    >
      <MotionDiv
        className="relative flex items-center justify-center"
        initial={{ scale: 0.82, opacity: 0 }}
        animate={{ scale: 1, opacity: 1, transition: { duration: 0.34, ease: "easeOut", delay: 0.12 } }}
      >
        <MotionDiv
          className="absolute size-20 rounded-full bg-red-500/15 blur-2xl"
          animate={{ scale: [1, 1.14, 1], opacity: [0.45, 0.75, 0.45] }}
          transition={{ duration: 2.6, repeat: Infinity, ease: "easeInOut" }}
        />
        <BotIcon className="size-20" />
      </MotionDiv>

      <MotionDiv
        className="mt-6"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0, transition: { duration: 0.28, ease: "easeOut", delay: 0.42 } }}
      >
        <p className="text-base font-medium leading-snug text-gray-800">
          안녕하세요. Exmatch AI 입니다.
          <br />
          전시회 정보나 참가기업, 제품이
          <br />
          궁금하시면 질문해주세요.
        </p>
        <p className="mt-4 text-xs text-gray-400">자주 묻는 질문을 확인하세요</p>
      </MotionDiv>

      <MotionDiv
        className="mt-4 flex w-full flex-col items-center gap-4"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0, transition: { duration: 0.28, ease: "easeOut", delay: 0.6 } }}
      >
        <div className="flex flex-wrap items-center justify-center gap-2">
          {(["faq_visitor", "faq_exhibitor"] as const).map((mode) => (
            <Button
              key={mode}
              variant="chip"
              onClick={(e) => { e.stopPropagation(); onSelectMode(mode) }}
            >
              {mode === "faq_visitor" ? "참관객 FAQ" : "참가업체 FAQ"}
            </Button>
          ))}
        </div>

        <div className="flex flex-col items-center gap-1">
          <p className="text-xs text-gray-400">참가기업과 제품이 궁금하신가요?</p>
          <Button
            variant="chip"
            onClick={(e) => { e.stopPropagation(); onSelectMode("catalog") }}
          >
            제품/기업 검색
          </Button>
        </div>
      </MotionDiv>
    </MotionDiv>
  </MotionDiv>
)
