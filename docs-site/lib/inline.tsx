// inline.tsx — Renders `code` spans and **bold** inside landing copy.
//
// The landing copy is prose written in MDX, but each field is a value in a slot
// rather than a document, so it never reaches the MDX pipeline. Two inline forms
// still have to survive: backticks (every other sentence names a command) and
// bold. Anything beyond that belongs in a docs page, not on the landing.
import type { ReactNode } from 'react'

export function inline(text: string): ReactNode[] {
  const parts: ReactNode[] = []
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g
  let last = 0
  let match: RegExpExecArray | null
  let key = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index))
    const token = match[0]
    if (token.startsWith('`')) {
      parts.push(
        <code
          key={key++}
          className="rounded-xs border border-border bg-panel px-1 py-0.5 font-mono text-[0.87em] text-primary"
        >
          {token.slice(1, -1)}
        </code>,
      )
    } else {
      parts.push(
        <strong key={key++} className="font-semibold text-primary">
          {token.slice(2, -2)}
        </strong>,
      )
    }
    last = match.index + token.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}
