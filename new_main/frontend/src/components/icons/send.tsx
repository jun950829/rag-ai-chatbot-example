import React from "react"

const SendIcon = (props: React.HTMLAttributes<SVGElement>) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" {...props}>
    <mask id="mask0_send" style={{ maskType: "alpha" }} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
      <rect width="24" height="24" fill="#D9D9D9" />
    </mask>
    <g mask="url(#mask0_send)">
      <path d="M5.7665 18.7228C5.4645 18.8434 5.17792 18.8178 4.90675 18.6458C4.63558 18.4738 4.5 18.2233 4.5 17.8943V13.673L11.423 12L4.5 10.327V6.10576C4.5 5.77676 4.63558 5.52626 4.90675 5.35426C5.17792 5.18226 5.4645 5.1566 5.7665 5.27726L19.723 11.1615C20.0948 11.328 20.2807 11.6081 20.2807 12.0018C20.2807 12.3954 20.0948 12.6743 19.723 12.8385L5.7665 18.7228Z" fill="white" />
    </g>
  </svg>
)

export { SendIcon }
