// Mark.tsx — The ALC mark, inline.
//
// Inline and not <img src="…mark.svg"> for a concrete reason: an SVG loaded
// through <img> is an isolated document, so `currentColor` resolves to the UA
// default — black — and the mark disappears on a dark surface. Inline it
// inherits colour and follows the theme for free.
//
// Geometry is identical to docs-site/public/brand/mark.svg. The site and the
// app are meant to read as one instrument, and two marks that differ slightly
// read as two products.

export function Mark({ size = 20, className = '' }: { size?: number; className?: string }) {
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
      {/* An open ring around a solid core: the loop runs on its own, the gap is
          where the human stays — on the loop, not in it — and the core is the
          Single Mandate the loop is built around. */}
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
