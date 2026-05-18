import React from "react"
import ReactMarkdown, { defaultUrlTransform } from "react-markdown"
import remarkGfm from "remark-gfm"

import { cn } from "@/lib/utils"

const PHONE_REGEX = /\b(?:\+?\d{1,3}[-.\s]?)?\d{2,4}[-.\s]\d{3,4}[-.\s]\d{4}\b/g
const UTM_PATTERN = /utm/i

const normalizeExternalHref = (href?: string): string => {
  const value = (href || "").trim()
  if (!value) return "#"
  if (/^(?:[a-z][a-z\d+\-.]*:|#|\/)/i.test(value)) return value
  return `https://${value}`
}

const linkifyPhoneNumbers = (text: string): string =>
  text.replace(PHONE_REGEX, (phone) => {
    const tel = phone.replace(/[^\d+]/g, "")
    return `[${phone}](tel:${tel})`
  })

const getSoftHiddenUrlParts = (text: string) => {
  const matchIndex = text.search(UTM_PATTERN)
  if (matchIndex === -1) return null
  const visibleEnd = matchIndex > 0 && text[matchIndex - 1] === "?" ? matchIndex - 1 : matchIndex
  return { visible: text.slice(0, visibleEnd), hidden: text.slice(visibleEnd) }
}

const getPlainText = (children: React.ReactNode): string =>
  React.Children.toArray(children)
    .filter((c): c is string | number => typeof c === "string" || typeof c === "number")
    .join("")
    .trim()

const normalizeBullets = (text: string): string =>
  text.replace(/^[·•]\s*/gm, "- ")

const RichContent: React.FC<{ content: string; className?: string }> = ({ content, className }) => {
  const parsedContent = normalizeBullets(linkifyPhoneNumbers(content))

  return (
    <div
      className={cn(
        "prose prose-sm max-w-none break-words text-sm leading-relaxed text-gray-900",
        "mt-2.5",
        className
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => (url.startsWith("tel:") ? url : defaultUrlTransform(url))}
        components={{
          p: ({ children }) => <p className="my-1.5 whitespace-pre-line">{children}</p>,
          h1: ({ children }) => <h1 className="mb-2 mt-3 text-base font-bold text-gray-900">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-1.5 mt-2.5 text-sm font-bold text-gray-900">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-1 mt-2 text-sm font-semibold text-gray-800">{children}</h3>,
          ul: ({ children }) => <ul className="my-1 ml-4 list-disc space-y-0.5">{children}</ul>,
          ol: ({ children }) => <ol className="my-1 ml-4 list-decimal space-y-0.5">{children}</ol>,
          li: ({ children }) => <li className="break-words pl-0.5">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-gray-300 pl-3 text-gray-500">{children}</blockquote>
          ),
          table: ({ children }) => (
            <div className="my-2 w-full overflow-x-auto">
              <table className="w-full border-collapse border border-gray-200 text-left">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-gray-100">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-b border-gray-200">{children}</tr>,
          th: ({ children }) => <th className="border border-gray-200 px-3 py-2 text-xs font-semibold">{children}</th>,
          td: ({ children }) => <td className="border border-gray-200 px-3 py-2 text-xs">{children}</td>,
          strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
          em: ({ children }) => <em className="italic text-gray-700">{children}</em>,
          hr: () => <hr className="my-2.5 border-gray-200" />,
          a: ({ children, href }) => {
            const normalizedHref = normalizeExternalHref(href)
            const isTel = normalizedHref.startsWith("tel:")
            const childText = getPlainText(children)
            const softHiddenParts = childText ? getSoftHiddenUrlParts(childText) : null
            return (
              <a
                href={normalizedHref}
                target={isTel ? undefined : "_blank"}
                rel={isTel ? undefined : "noreferrer"}
                className="break-all text-blue-600 underline"
              >
                {softHiddenParts ? softHiddenParts.visible : children}
              </a>
            )
          },
          code: ({ children }) => <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">{children}</code>,
          pre: ({ children }) => <pre className="overflow-x-auto rounded bg-gray-100 p-2 text-xs">{children}</pre>,
        }}
      >
        {parsedContent}
      </ReactMarkdown>
    </div>
  )
}

export { RichContent }
