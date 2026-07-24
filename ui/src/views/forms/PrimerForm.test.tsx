import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { PrimerForm } from './PrimerForm'
import { renderControlledForm } from '../../test/utils'

const PRIMER = `# onboarding

## Where things live
<!-- Describe the key directories and files the agent should know about. -->

## Conventions
<!-- List naming rules, style guides, or patterns followed in this codebase. -->
`

function lastRaw(onDoc: ReturnType<typeof vi.fn>): string {
  return onDoc.mock.calls.at(-1)![0] as string
}

function renderPrimer(onDoc: ReturnType<typeof vi.fn>, initial = PRIMER) {
  return renderControlledForm(initial, (value, onChange) => <PrimerForm value={value} onChange={onChange} />, onDoc)
}

describe('PrimerForm', () => {
  it('edits the title without touching the rest of the body', () => {
    const onDoc = vi.fn()
    renderPrimer(onDoc)

    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'onboarding guide' } })

    const raw = lastRaw(onDoc)
    expect(raw.startsWith('# onboarding guide\n')).toBe(true)
    expect(raw).toContain('## Where things live')
    expect(raw).toContain('<!-- Describe the key directories and files the agent should know about. -->')
    expect(raw).toContain('## Conventions')
  })

  it('edits the body without touching the title', () => {
    const onDoc = vi.fn()
    renderPrimer(onDoc)

    fireEvent.change(screen.getByLabelText('Body'), {
      target: { value: '\n## Where things live\nsrc/alc/ — the core package.\n' },
    })

    const raw = lastRaw(onDoc)
    expect(raw.startsWith('# onboarding\n')).toBe(true)
    expect(raw).toContain('src/alc/ — the core package.')
  })

  it('has no Title field and edits the whole body when the file has no leading heading', () => {
    const onDoc = vi.fn()
    renderPrimer(onDoc, 'Some free-form notes with no heading.\n')

    expect(screen.queryByLabelText('Title')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Body'), { target: { value: 'Edited notes.\n' } })
    expect(lastRaw(onDoc)).toBe('Edited notes.\n')
  })
})
