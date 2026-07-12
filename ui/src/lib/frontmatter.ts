// frontmatter.ts — Split/replace YAML front-matter while preserving the body.
//
// Blueprints are Markdown with a `--- ... ---` YAML header. A form edits only the
// header; the body must survive byte-for-byte. These helpers isolate the header
// so the recompose never touches the markdown that follows.
const FRONT_MATTER = /^(\s*)---\n([\s\S]*?)\n---/

/** Return the inner YAML text of a file's front-matter, or null when it has none. */
export function getFrontMatter(raw: string): string | null {
  const m = FRONT_MATTER.exec(raw)
  return m ? m[2] : null
}

/**
 * Replace the front-matter YAML with `newFm`, preserving everything after the
 * closing fence (the markdown body) exactly. Returns null when `raw` has no
 * front-matter to replace.
 */
export function replaceFrontMatter(raw: string, newFm: string): string | null {
  const m = FRONT_MATTER.exec(raw)
  if (!m) return null
  const leading = m[1]
  const rest = raw.slice(m.index + m[0].length) // from just after the closing '---'
  const fm = newFm.replace(/\n+$/, '')
  return `${leading}---\n${fm}\n---${rest}`
}
