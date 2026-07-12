import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SourceEditor } from './SourceEditor'
import { installFetch, renderWithProviders, res } from '../test/utils'
import type { FetchCall } from '../test/utils'
import { tabId, uiStore } from '../app/uiStore'

// Monaco is heavy and DOM-hostile in jsdom; the editor is only reached via
// React.lazy, so mock it with a plain textarea that mirrors value/onChange.
vi.mock('../components/CodeEditor', () => ({
  default: ({
    value,
    onChange,
    readOnly,
  }: {
    value: string
    onChange: (v: string) => void
    readOnly?: boolean
  }) => (
    <textarea
      aria-label="source"
      value={value}
      readOnly={readOnly}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}))

const MANIFEST = 'version: 1\ndefault_engine: mock\n'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

describe('SourceEditor — manifest', () => {
  it('loads the raw and marks the tab dirty on edit', async () => {
    installFetch({ '/manifest': { raw: MANIFEST, parsed: {} } })
    renderWithProviders(<SourceEditor resource="manifest" name="manifest" />)

    const editor = (await screen.findByLabelText('source')) as HTMLTextAreaElement
    expect(editor.value).toContain('default_engine: mock')

    const id = tabId({ type: 'source', resource: 'manifest', name: 'manifest' })
    expect(uiStore.getState().dirty[id]).toBeFalsy()

    fireEvent.change(editor, { target: { value: MANIFEST + 'plan_retries: 3\n' } })
    expect(uiStore.getState().dirty[id]).toBe(true)
  })

  it('saves with PUT and clears the dirty flag', async () => {
    const mock = installFetch({
      '/manifest': (call: FetchCall) =>
        call.method === 'PUT' ? { raw: (call.body as { raw: string }).raw, parsed: {} } : { raw: MANIFEST, parsed: {} },
    })
    renderWithProviders(<SourceEditor resource="manifest" name="manifest" />)

    const editor = (await screen.findByLabelText('source')) as HTMLTextAreaElement
    const next = MANIFEST + 'plan_retries: 3\n'
    fireEvent.change(editor, { target: { value: next } })
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    const put = mock.calls.find((c) => c.method === 'PUT')
    expect(put?.body).toEqual({ raw: next })
    const id = tabId({ type: 'source', resource: 'manifest', name: 'manifest' })
    expect(uiStore.getState().dirty[id]).toBeFalsy()
  })

  it('keeps the draft and dirty state across tab unmount/remount', async () => {
    installFetch({ '/manifest': { raw: MANIFEST, parsed: {} } })
    const { unmount } = renderWithProviders(<SourceEditor resource="manifest" name="manifest" />)
    const editor = (await screen.findByLabelText('source')) as HTMLTextAreaElement
    const edited = MANIFEST + 'plan_retries: 9\n'
    fireEvent.change(editor, { target: { value: edited } })

    const id = tabId({ type: 'source', resource: 'manifest', name: 'manifest' })
    expect(uiStore.getState().dirty[id]).toBe(true)

    unmount()
    // Dirty state survives the unmount (switching to another tab).
    expect(uiStore.getState().dirty[id]).toBe(true)

    renderWithProviders(<SourceEditor resource="manifest" name="manifest" />)
    const reopened = (await screen.findByLabelText('source')) as HTMLTextAreaElement
    expect(reopened.value).toBe(edited)
  })

  it('shows the 422 violations without losing the typed content', async () => {
    installFetch({
      '/manifest': (call: FetchCall) =>
        call.method === 'PUT'
          ? res(422, {
              detail: 'manifest introduces Policy Gate errors',
              violations: [{ rule: 'engine-declared', severity: 'error', message: 'ghost not declared' }],
            })
          : { raw: MANIFEST, parsed: {} },
    })
    renderWithProviders(<SourceEditor resource="manifest" name="manifest" />)

    const editor = (await screen.findByLabelText('source')) as HTMLTextAreaElement
    const bad = 'default_engine: ghost\n'
    fireEvent.change(editor, { target: { value: bad } })
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('manifest introduces Policy Gate errors')).toBeInTheDocument()
    expect(screen.getByText(/ghost not declared/)).toBeInTheDocument()
    // Content preserved for correction.
    expect((screen.getByLabelText('source') as HTMLTextAreaElement).value).toBe(bad)
  })
})

describe('SourceEditor — blueprint form round-trip', () => {
  const BP = `---
name: chore
purpose: Do a chore.
custom_field: keep-me
checks:
  - name: smoke
    command: ["true"]
---

## Chore workflow

1. Do the thing.
`

  it('edits a field via the form and preserves the body + unknown keys', async () => {
    const mock = installFetch({
      '/blueprints/chore': (call: FetchCall) =>
        call.method === 'PUT' ? { raw: (call.body as { raw: string }).raw, parsed: {} } : { raw: BP, parsed: {} },
      '/manifest': { raw: MANIFEST, parsed: { compute_tiers: { standard: {}, deep: {} } } },
    })
    renderWithProviders(<SourceEditor resource="blueprints" name="chore" />)

    await userEvent.click(await screen.findByRole('button', { name: 'form' }))
    const purpose = (await screen.findByLabelText('Purpose')) as HTMLTextAreaElement
    fireEvent.change(purpose, { target: { value: 'Do a bigger chore.' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    const put = mock.calls.find((c) => c.method === 'PUT')
    const raw = (put?.body as { raw: string }).raw
    expect(raw).toContain('purpose: Do a bigger chore.')
    expect(raw).toContain('custom_field: keep-me')
    expect(raw).toContain('## Chore workflow\n\n1. Do the thing.')
  })
})
