import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { parseDocument } from 'yaml'
import { SpecialistForm } from './SpecialistForm'
import { renderControlledForm } from '../../test/utils'

const SPECIALIST = `name: docs
# keep this note
custom_field: keep-me
area: Documentation and guides
blueprint: chore
knowledge_path: .alc/knowledge/docs.md
`

function lastRaw(onDoc: ReturnType<typeof vi.fn>): string {
  return onDoc.mock.calls.at(-1)![0] as string
}

function lastParsed(onDoc: ReturnType<typeof vi.fn>) {
  return parseDocument(lastRaw(onDoc)).toJSON()
}

function renderSpecialist(onDoc: ReturnType<typeof vi.fn>, blueprintNames: string[] = []) {
  return renderControlledForm(
    SPECIALIST,
    (value, onChange) => (
      <SpecialistForm value={value} onChange={onChange} blueprintNames={blueprintNames} />
    ),
    onDoc,
  )
}

describe('SpecialistForm', () => {
  it('edits a field and preserves the comment and the unknown key', () => {
    const onDoc = vi.fn()
    renderSpecialist(onDoc)

    fireEvent.change(screen.getByLabelText('Area'), { target: { value: 'Docs and API reference' } })

    const raw = lastRaw(onDoc)
    expect(raw).toContain('# keep this note')
    expect(raw).toContain('custom_field: keep-me')
    expect(lastParsed(onDoc).area).toBe('Docs and API reference')
  })

  it('edits name and knowledge_path, keeping the comment intact', () => {
    const onDoc = vi.fn()
    renderSpecialist(onDoc)

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'renamed' } })
    fireEvent.change(screen.getByLabelText('Knowledge path'), {
      target: { value: '.alc/knowledge/renamed.md' },
    })

    const parsed = lastParsed(onDoc)
    expect(parsed.name).toBe('renamed')
    expect(parsed.knowledge_path).toBe('.alc/knowledge/renamed.md')
    expect(lastRaw(onDoc)).toContain('# keep this note')
  })

  it('renders the blueprint field as a Select fed by the project blueprint names', () => {
    const onDoc = vi.fn()
    renderSpecialist(onDoc, ['chore', 'feature'])

    const select = screen.getByLabelText('Blueprint') as HTMLSelectElement
    expect(select.tagName).toBe('SELECT')
    const optionValues = Array.from(select.options).map((o) => o.value)
    expect(optionValues).toEqual(expect.arrayContaining(['chore', 'feature']))

    fireEvent.change(select, { target: { value: 'feature' } })
    expect(lastParsed(onDoc).blueprint).toBe('feature')
    expect(lastRaw(onDoc)).toContain('custom_field: keep-me')
  })

  it('falls back to a plain text input when no blueprint names are available', () => {
    const onDoc = vi.fn()
    renderSpecialist(onDoc, [])

    const input = screen.getByLabelText('Blueprint') as HTMLInputElement
    expect(input.tagName).toBe('INPUT')

    fireEvent.change(input, { target: { value: 'bug' } })
    expect(lastParsed(onDoc).blueprint).toBe('bug')
  })

  it('shows a syntax-error notice instead of crashing on invalid YAML', () => {
    const onDoc = vi.fn()
    renderControlledForm(
      'name: [unterminated',
      (value, onChange) => <SpecialistForm value={value} onChange={onChange} blueprintNames={[]} />,
      onDoc,
    )

    expect(screen.getByText(/syntax error/i)).toBeInTheDocument()
  })
})
