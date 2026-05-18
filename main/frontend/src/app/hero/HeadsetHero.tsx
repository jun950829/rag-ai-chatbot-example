/** 랜딩용 간단 일러스트(참조 이미지의 헤드셋+큐브 느낌). */

export function HeadsetHero({ className = '' }: { className?: string }) {
  return (
    <div className={`flex justify-center ${className}`} aria-hidden>
      <svg width="112" height="112" viewBox="0 0 112 112" className="drop-shadow-md">
        <defs>
          <linearGradient id="hp" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#22c55e" />
            <stop offset="100%" stopColor="#a3e635" />
          </linearGradient>
        </defs>
        <rect x="28" y="36" width="56" height="52" rx="12" fill="url(#hp)" stroke="#15803d" strokeWidth="2" />
        <text x="56" y="74" textAnchor="middle" fontSize="28" fontWeight="800" fill="#0f172a">
          k
        </text>
        <path
          d="M10 62 C10 28 36 12 56 12 C76 12 102 28 102 62"
          fill="none"
          stroke="#2563eb"
          strokeWidth="10"
          strokeLinecap="round"
        />
        <path
          d="M18 58 C16 40 24 24 36 20"
          fill="none"
          stroke="#1d4ed8"
          strokeWidth="8"
          strokeLinecap="round"
        />
        <path
          d="M94 58 C96 40 88 24 76 20"
          fill="none"
          stroke="#1d4ed8"
          strokeWidth="8"
          strokeLinecap="round"
        />
      </svg>
    </div>
  )
}
