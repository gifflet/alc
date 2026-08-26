// contrast.ts — WCAG relative luminance and contrast ratio.
//
// The palette is enforced, not merely documented: contrast.test.ts walks every
// (text, surface) pair in both themes and fails the build below its floor. The
// dark theme shipped with `faint` at 2.83:1 — below even the 3:1 UI floor — and
// nothing caught it, because nothing was checking.
//
// Formula: WCAG 2.x relative luminance, sRGB.

/** Floors from WCAG 2.2: 4.5:1 for body text, 3:1 for UI and large text. */
export const AA_BODY = 4.5
export const AA_UI = 3.0

function channel(value: number): number {
  const c = value / 255
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

/** Relative luminance of a #rrggbb colour. */
export function luminance(hex: string): number {
  const h = hex.replace('#', '')
  if (h.length !== 6) throw new Error(`expected #rrggbb, got ${hex}`)
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

/** Contrast ratio between two colours, 1..21. */
export function contrast(a: string, b: string): number {
  const la = luminance(a)
  const lb = luminance(b)
  const [hi, lo] = la > lb ? [la, lb] : [lb, la]
  return (hi + 0.05) / (lo + 0.05)
}

/** Round to two decimals, for readable assertion messages. */
export function ratio(a: string, b: string): number {
  return Math.round(contrast(a, b) * 100) / 100
}
