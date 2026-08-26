// hex.ts — Normalise a CSS colour value for consumers that demand #rrggbb.
//
// Monaco cannot read CSS custom properties, so its theme is built from values
// read off :root — and getPropertyValue serves the shorthand ("#fff" for
// #ffffff), which Monaco rejects outright.
export function expandHex(value: string): string | null {
  const hex = value.trim().replace('#', '')
  if (/^[0-9a-fA-F]{6}$/.test(hex)) return `#${hex}`
  if (/^[0-9a-fA-F]{3}$/.test(hex)) return `#${hex[0]}${hex[0]}${hex[1]}${hex[1]}${hex[2]}${hex[2]}`
  return null
}
