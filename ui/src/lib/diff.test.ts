import { describe, expect, it } from 'vitest'
import { anchorKey, isCommentable, parseDiff } from './diff'

const DIFF = `diff --git a/app.py b/app.py
index 1234567..89abcde 100644
--- a/app.py
+++ b/app.py
@@ -1,4 +1,5 @@
 def f():
-    return 1
+    return 2
+    # note
 
 def g():
`

describe('parseDiff', () => {
  it('attributes every line to its post-image path', () => {
    const lines = parseDiff(DIFF).filter((l) => l.kind === 'add' || l.kind === 'context')
    expect(new Set(lines.map((l) => l.path))).toEqual(new Set(['app.py']))
  })

  it('ignores the trailing newline instead of inventing a line past the end', () => {
    const lines = parseDiff(DIFF)
    const last = lines[lines.length - 1]
    expect(last.text).toBe(' def g():')
  })

  it('numbers additions and context from the hunk header', () => {
    const lines = parseDiff(DIFF)
    const numbered = lines
      .filter((l) => l.newLine !== undefined && (l.kind === 'add' || l.kind === 'context'))
      .map((l) => [l.kind, l.newLine, l.text.slice(0, 12)])
    expect(numbered).toEqual([
      ['context', 1, ' def f():'],
      ['add', 2, '+    return '],
      ['add', 3, '+    # note'],
      ['context', 4, ' '],
      ['context', 5, ' def g():'],
    ])
  })

  it('does not advance the counter on a deletion', () => {
    // The deleted line has no post-image number; the next addition takes 2.
    const lines = parseDiff(DIFF)
    const del = lines.find((l) => l.kind === 'del')!
    expect(del.newLine).toBeUndefined()
    const firstAdd = lines.find((l) => l.kind === 'add')!
    expect(firstAdd.newLine).toBe(2)
  })

  it('marks only post-image lines as commentable', () => {
    const lines = parseDiff(DIFF)
    expect(lines.filter(isCommentable).every((l) => l.kind === 'add' || l.kind === 'context')).toBe(true)
    expect(lines.filter((l) => l.kind === 'del').some(isCommentable)).toBe(false)
    expect(lines.filter((l) => l.kind === 'hunk').some(isCommentable)).toBe(false)
  })

  it('handles a deleted file without inventing an anchor', () => {
    const deleted = `diff --git a/old.py b/old.py
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-gone
`
    const lines = parseDiff(deleted)
    expect(lines.some(isCommentable)).toBe(false)
  })

  it('returns nothing for an empty diff', () => {
    expect(parseDiff('')).toEqual([])
  })

  it('builds a stable anchor key', () => {
    expect(anchorKey('src/foo.py', 42)).toBe('src/foo.py:42')
  })
})

describe('parseDiff file headers', () => {
  const NEW_FILE = `diff --git a/work.txt b/work.txt
new file mode 100644
index 0000000..b8f99f5
--- /dev/null
+++ b/work.txt
@@ -0,0 +1 @@
+work
`

  it('never treats a git header line as content', () => {
    // Measured on device: "new file mode 100644" was rendered as context, given
    // a line number, and offered a comment anchor.
    const header = parseDiff(NEW_FILE).find((l) => l.text.startsWith('new file mode'))!
    expect(header.kind).toBe('meta')
    expect(header.newLine).toBeUndefined()
    expect(isCommentable(header)).toBe(false)
  })

  it('still addresses the added line of a new file', () => {
    const add = parseDiff(NEW_FILE).find((l) => l.kind === 'add')!
    expect(add.path).toBe('work.txt')
    expect(add.newLine).toBe(1)
    expect(isCommentable(add)).toBe(true)
  })

  it('offers exactly one anchor for a one-line new file', () => {
    expect(parseDiff(NEW_FILE).filter(isCommentable)).toHaveLength(1)
  })
})
