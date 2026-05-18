import { FC, HTMLAttributes } from "react"

const LikeFilledIcon: FC<HTMLAttributes<SVGElement>> = (props) => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <mask id="mask0_like_filled" maskUnits="userSpaceOnUse" x="0" y="0" width="20" height="20">
      <rect width="20" height="20" fill="#D9D9D9" />
    </mask>
    <g mask="url(#mask0_like_filled)">
      <path d="M14.9993 17.5002H6.66602V6.66683L12.4993 0.833496L13.541 1.87516C13.6382 1.97238 13.7181 2.10433 13.7806 2.271C13.8431 2.43766 13.8743 2.59738 13.8743 2.75016V3.04183L12.9577 6.66683H17.4993C17.9438 6.66683 18.3327 6.8335 18.666 7.16683C18.9993 7.50016 19.166 7.88905 19.166 8.3335V10.0002C19.166 10.0974 19.1556 10.2016 19.1348 10.3127C19.1139 10.4238 19.0827 10.5279 19.041 10.6252L16.541 16.5002C16.416 16.7779 16.2077 17.0141 15.916 17.2085C15.6243 17.4029 15.3188 17.5002 14.9993 17.5002ZM4.99935 6.66683V17.5002H1.66602V6.66683H4.99935Z" fill="#848484" />
    </g>
  </svg>
)

export { LikeFilledIcon }
