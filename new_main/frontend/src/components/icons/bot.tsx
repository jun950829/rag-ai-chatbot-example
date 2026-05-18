import { FC, HTMLAttributes } from "react"

const BotIcon: FC<HTMLAttributes<SVGElement>> = (props) => (
  <svg width="36" height="36" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <circle cx="18" cy="18" r="18" fill="#fff1f2" />
    <path d="M18 8a4 4 0 0 1 4 4v1h1a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3H13a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3h1v-1a4 4 0 0 1 4-4Zm0 2a2 2 0 0 0-2 2v1h4v-1a2 2 0 0 0-2-2Zm-5 5a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-6a1 1 0 0 0-1-1H13Zm2.5 2.5a1 1 0 1 1 0 2 1 1 0 0 1 0-2Zm5 0a1 1 0 1 1 0 2 1 1 0 0 1 0-2Z" fill="#e60012" />
  </svg>
)

export { BotIcon }
