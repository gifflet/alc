import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { parseDocument } from 'yaml'
import { BlueprintForm } from './BlueprintForm'
import { getFrontMatter } from '../../lib/frontmatter'
import { renderControlledForm } from '../../test/utils'

const BP = `---
name: chore
purpose: Do a chore.
# a hand-written note about this mandate
custom_field: keep-me
checks:
  - name: smoke
    command: ["true"]
---

## Chore workflow

1. Do the thing.
`

function lastRaw(onDoc: ReturnType<typeof vi.fn>): string {
  return onDoc.mock.calls.at(-1)![0] as string
}

function lastFrontMatter(onDoc: ReturnType<typeof vi.fn>) {
  return parseDocument(getFrontMatter(lastRaw(onDoc)) ?? '').toJSON()
}

function renderBP(onDoc: ReturnType<typeof vi.fn>) {
  return renderControlledForm(
    BP,
    (value, onChange) => <BlueprintForm value={value} onChange={onChange} tiers={[]} checkSets={[]} />,
    onDoc,
  )
}

describe('BlueprintForm', () => {
  it('edits a new field and preserves the comment, the unknown key and the body', async () => {
    const onDoc = vi.fn()
    renderBP(onDoc)

    fireEvent.change(screen.getByLabelText('Archetype'), { target: { value: 'sweeper' } })

    const raw = lastRaw(onDoc)
    expect(raw).toContain('# a hand-written note about this mandate')
    expect(raw).toContain('custom_field: keep-me')
    expect(raw).toContain('## Chore workflow\n\n1. Do the thing.')
    expect(lastFrontMatter(onDoc).archetype).toBe('sweeper')
  })

  it('edits mode, expect and capture, clearing back to none', async () => {
    const onDoc = vi.fn()
    renderBP(onDoc)

    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'spike' } })
    fireEvent.change(screen.getByLabelText('Expect'), { target: { value: 'shrink' } })
    fireEvent.change(screen.getByLabelText('Capture'), { target: { value: 'scripts/capture.sh' } })

    let fm = lastFrontMatter(onDoc)
    expect(fm.mode).toBe('spike')
    expect(fm.expect).toBe('shrink')
    expect(fm.capture).toBe('scripts/capture.sh')

    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: '' } })
    fm = lastFrontMatter(onDoc)
    expect(fm.mode).toBeUndefined()
    // Comment/unknown key still intact after the second edit.
    expect(lastRaw(onDoc)).toContain('custom_field: keep-me')
  })

  it('adds and removes protected-path globs', async () => {
    const onDoc = vi.fn()
    renderBP(onDoc)

    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    fireEvent.change(screen.getByPlaceholderText('src/**/*.py'), { target: { value: 'dist/**' } })
    expect(lastFrontMatter(onDoc).protect).toEqual(['dist/**'])

    await userEvent.click(screen.getByLabelText('Remove dist/**'))
    expect(lastFrontMatter(onDoc).protect).toBeUndefined()
  })

  it('sets a check flaky rerun count from the blueprint form', () => {
    const onDoc = vi.fn()
    renderBP(onDoc)

    fireEvent.change(screen.getByLabelText('Flaky reruns'), { target: { value: '3' } })
    expect(lastFrontMatter(onDoc).checks[0].flaky).toBe(3)
  })
})

describe('BlueprintForm invalid check_set', () => {
  const BP_INVALID = `---
name: refactor
purpose: Clean up.
check_set: python
checks:
  - name: smoke
    command: ["true"]
---

body
`

  // Finding 35: an undeclared stored value rendered as "(none)" — the form
  // silently misrepresented the file and rewrote it on save.
  it('shows the undeclared value as its own labelled option', () => {
    const onDoc = vi.fn()
    renderControlledForm(
      BP_INVALID,
      (value, onChange) => (
        <BlueprintForm value={value} onChange={onChange} tiers={[]} checkSets={['project', 'security']} />
      ),
      onDoc,
    )
    const select = screen.getByLabelText('Check set') as HTMLSelectElement
    expect(select.value).toBe('python')
    const labels = Array.from(select.options).map((o) => o.label)
    expect(labels).toContain('python (not declared!)')
  })

  it('regression: a declared value renders plainly, with no extra option', () => {
    const onDoc = vi.fn()
    renderControlledForm(
      BP_INVALID.replace('check_set: python', 'check_set: project'),
      (value, onChange) => (
        <BlueprintForm value={value} onChange={onChange} tiers={[]} checkSets={['project', 'security']} />
      ),
      onDoc,
    )
    const select = screen.getByLabelText('Check set') as HTMLSelectElement
    expect(select.value).toBe('project')
    expect(Array.from(select.options).map((o) => o.label)).toEqual(['(none)', 'project', 'security'])
  })
})
