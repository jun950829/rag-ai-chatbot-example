import { FC, HTMLAttributes } from "react"

const AddIcon: FC<HTMLAttributes<SVGElement>> = (props) => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <mask id="mask0_add" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
      <rect width="24" height="24" fill="#D9D9D9" />
    </mask>
    <g mask="url(#mask0_add)">
      <path d="M11 13H5V11H11V5H13V11H19V13H13V19H11V13Z" fill="white" />
    </g>
  </svg>
)

export default AddIcon
