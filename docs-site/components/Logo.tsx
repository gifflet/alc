// Logo.tsx — The mark, inline.
//
// Inline and not <img src="/brand/mark.svg"> for one concrete reason: an SVG
// loaded through <img> is an isolated document, so `currentColor` resolves to
// the UA default (black) instead of the surrounding text colour. The first
// render of the brand sheet showed a black mark on the dark surface, invisible.
// Inline, it inherits colour and follows the theme for free.

export function Mark({ size = 32, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={className}
      role="img"
      aria-label="ALC"
      fill="currentColor"
    >
      {/* The ring is open, not closed: the loop runs on its own, and the gap is
          where the human stays — on the loop, not in it. The core is the Single
          Mandate the loop is built around. */}
      <path
        d="M27 19V23a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4V9a4 4 0 0 1 4-4h14a4 4 0 0 1 4 4v4"
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
      />
      <rect x="13" y="11" width="6" height="10" rx="1" />
    </svg>
  )
}

export function Wordmark({ className = '' }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <Mark size={26} />
      <span className="text-[17px] font-semibold tracking-tight">ALC</span>
    </span>
  )
}
