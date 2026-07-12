import { describe, expect, it } from 'vitest'
import { parseDocument } from 'yaml'
import { getFrontMatter, replaceFrontMatter } from './frontmatter'

const doc = `---
name: chore
purpose: Do a chore.
# a comment the form never surfaces
custom_field: keep-me
---

## Chore workflow

1. Do the thing.
`

describe('front-matter', () => {
  it('extracts the header yaml', () => {
    expect(getFrontMatter(doc)).toContain('name: chore')
    expect(getFrontMatter('no header here')).toBeNull()
  })

  it('replaces the header and preserves the body verbatim', () => {
    const fm = parseDocument(getFrontMatter(doc)!)
    fm.setIn(['purpose'], 'Do a bigger chore.')
    const next = replaceFrontMatter(doc, String(fm))!
    // Body untouched.
    expect(next).toContain('## Chore workflow\n\n1. Do the thing.')
    // Edited field applied.
    expect(next).toContain('purpose: Do a bigger chore.')
    // Unknown field + comment survive the round-trip.
    expect(next).toContain('custom_field: keep-me')
    expect(next).toContain('# a comment the form never surfaces')
  })

  it('returns null when there is no front-matter', () => {
    expect(replaceFrontMatter('plain markdown', 'name: x')).toBeNull()
  })
})
