"use client"

import { FC, useCallback, useState } from "react"
import { toast } from "sonner"
import { CheckIcon, CopyIcon } from "@/components/icons"
import { Button } from "@/components/ui/button"

const ClipboardCopy: FC<{ text: string }> = ({ text }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    toast.info("복사되었습니다.", { duration: 1000, style: { border: "none" } })
    setTimeout(() => setCopied(false), 1000)
  }, [text])

  return (
    <Button variant="icon" type="button" onClick={handleCopy}>
      {copied ? <CheckIcon className="size-5 text-gray-400" /> : <CopyIcon className="size-5 text-gray-600" />}
    </Button>
  )
}

export { ClipboardCopy }
