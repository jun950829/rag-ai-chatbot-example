import React from "react"

const DisLikeFilledIcon = (props: React.HTMLAttributes<SVGElement>) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20" fill="none" {...props}>
    <mask id="mask0_dislike_filled" style={{ maskType: "alpha" }} maskUnits="userSpaceOnUse" x="0" y="0" width="20" height="20">
      <rect width="20" height="20" fill="#D9D9D9" />
    </mask>
    <g mask="url(#mask0_dislike_filled)">
      <path d="M5 2.5H13.3333V13.3333L7.5 19.1667L6.45833 18.125C6.36111 18.0278 6.28125 17.8958 6.21875 17.7292C6.15625 17.5625 6.125 17.4028 6.125 17.25V16.9583L7.04167 13.3333H2.5C2.05556 13.3333 1.66667 13.1667 1.33333 12.8333C1 12.5 0.833333 12.1111 0.833333 11.6667V10C0.833333 9.90278 0.843056 9.79861 0.8625 9.6875C0.881944 9.57639 0.916667 9.47222 0.966667 9.375L3.45833 4.2C3.58333 3.86667 3.79167 3.58333 4.08333 3.35C4.375 3.11667 4.68056 3 5 2.5H5ZM15 13.3333V2.5H18.3333V13.3333H15Z" fill="#848484" />
    </g>
  </svg>
)

export { DisLikeFilledIcon }
