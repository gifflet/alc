// diff.ts — Parse a unified diff into addressable lines.
//
// Review needs more than syntax colour: a comment has to name a FILE and a LINE
// that the agent can find again. So each rendered line carries the path it
// belongs to and its line number in the post-image, which is what `path:line`
// in the feedback body refers to.
//
// Pure, so the addressing is unit-tested without a DOM — the subtle part is that
// line numbers advance on additions and context but not on deletions.

type DiffLineKind = 'file' | 'hunk' | 'add' | 'del' | 'context' | 'meta'

export interface DiffLine {
  kind: DiffLineKind
  text: string
  /** Path in the post-image (the b/ side); undefined before the first header. */
  path?: string
  /** Line number in the post-image — only for lines that exist there. */
  newLine?: number
}

const FILE_RE = /^\+\+\+ (?:b\/)?(.+)$/
const HUNK_RE = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/

/** Whether a line can carry a comment (it exists in the post-image). */
export function isCommentable(line: DiffLine): boolean {
  return (line.kind === 'add' || line.kind === 'context') && Boolean(line.path) && line.newLine !== undefined
}

/** A stable key for a comment anchor. */
export function anchorKey(path: string, line: number): string {
  return `${path}:${line}`
}

export function parseDiff(text: string): DiffLine[] {
  const out: DiffLine[] = []
  if (!text) return out

  let path: string | undefined
  let newLine = 0
  // Only lines INSIDE a hunk are content. Everything before the first @@ is
  // git's file header ("new file mode", "similarity index", "rename from", …);
  // treating those as context gave them line numbers and made them commentable,
  // which was visible on the device.
  let inHunk = false

  // A unified diff ends with a newline, and split() turns that into a trailing
  // empty element. Treating it as a context line would invent a commentable
  // anchor one past the end of the file.
  const rawLines = text.split('\n')
  if (rawLines[rawLines.length - 1] === '') rawLines.pop()

  for (const raw of rawLines) {
    const fileMatch = FILE_RE.exec(raw)
    if (raw.startsWith('diff --git')) {
      inHunk = false
      out.push({ kind: 'meta', text: raw, path })
      continue
    }

    if (fileMatch) {
      // `/dev/null` on the b/ side means the file was deleted — nothing in the
      // post-image to anchor a comment to.
      path = fileMatch[1] === '/dev/null' ? undefined : fileMatch[1]
      out.push({ kind: 'file', text: raw, path })
      continue
    }

    const hunkMatch = HUNK_RE.exec(raw)
    if (hunkMatch) {
      inHunk = true
      newLine = Number(hunkMatch[1])
      out.push({ kind: 'hunk', text: raw, path })
      continue
    }

    if (!inHunk) {
      out.push({ kind: 'meta', text: raw, path })
      continue
    }

    if (raw.startsWith('+')) {
      out.push({ kind: 'add', text: raw, path, newLine })
      newLine += 1
      continue
    }
    if (raw.startsWith('-')) {
      // A deletion has no post-image line, so the counter must NOT advance.
      out.push({ kind: 'del', text: raw, path })
      continue
    }
    if (raw.startsWith('\\')) {
      out.push({ kind: 'meta', text: raw, path })
      continue
    }

    out.push({ kind: 'context', text: raw, path, newLine })
    newLine += 1
  }

  return out
}
