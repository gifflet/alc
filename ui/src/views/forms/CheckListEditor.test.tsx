import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { parseDocument } from 'yaml'
import type { Document } from 'yaml'
import { CheckListEditor } from './CheckListEditor'

/** Mirrors how a real form owns/re-parses its Document across edits. */
function Harness({ initial, onDoc }: { initial: string; onDoc: (raw: string) => void }) {
  const [raw, setRaw] = useState(initial)
  const doc = parseDocument(raw)
  const update = (mutate: (d: Document) => void) => {
    const next = parseDocument(raw)
    mutate(next)
    const out = String(next)
    setRaw(out)
    onDoc(out)
  }
  return <CheckListEditor doc={doc} path={['checks']} update={update} />
}

function lastDoc(onDoc: ReturnType<typeof vi.fn>) {
  return parseDocument(onDoc.mock.calls.at(-1)![0] as string).toJSON()
}

describe('CheckListEditor', () => {
  it('switches a check between command, shell and metric — exactly one shape at a time', async () => {
    const onDoc = vi.fn()
    render(<Harness initial={'checks:\n  - name: smoke\n    command: ["pytest", "-q"]\n'} onDoc={onDoc} />)

    await userEvent.selectOptions(screen.getByLabelText('Check mode'), 'metric')
    let parsed = lastDoc(onDoc)
    expect(parsed.checks[0].command).toBeUndefined()
    expect(parsed.checks[0].shell).toBeUndefined()
    expect(parsed.checks[0].metric).toEqual(['pytest', '-q'])
    expect(parsed.checks[0].direction).toBe('lower_is_better')
    expect(parsed.checks[0].tolerance_pct).toBe(0)

    fireEvent.change(screen.getByLabelText('Metric direction'), { target: { value: 'higher_is_better' } })
    fireEvent.change(screen.getByLabelText('Tolerance percent'), { target: { value: '5' } })
    parsed = lastDoc(onDoc)
    expect(parsed.checks[0].direction).toBe('higher_is_better')
    expect(parsed.checks[0].tolerance_pct).toBe(5)

    await userEvent.selectOptions(screen.getByLabelText('Check mode'), 'shell')
    parsed = lastDoc(onDoc)
    expect(parsed.checks[0].metric).toBeUndefined()
    expect(parsed.checks[0].direction).toBeUndefined()
    expect(parsed.checks[0].tolerance_pct).toBeUndefined()
    expect(parsed.checks[0].shell).toBe('pytest -q')
    expect(parsed.checks[0].command).toBeUndefined()

    await userEvent.selectOptions(screen.getByLabelText('Check mode'), 'command')
    parsed = lastDoc(onDoc)
    expect(parsed.checks[0].shell).toBeUndefined()
    expect(parsed.checks[0].command).toEqual(['pytest', '-q'])
  })

  it('round-trips the per-check flaky rerun count, omitting it when zero (the default)', () => {
    const onDoc = vi.fn()
    render(<Harness initial={'checks:\n  - name: smoke\n    command: ["true"]\n'} onDoc={onDoc} />)

    fireEvent.change(screen.getByLabelText('Flaky reruns'), { target: { value: '2' } })
    expect(lastDoc(onDoc).checks[0].flaky).toBe(2)

    fireEvent.change(screen.getByLabelText('Flaky reruns'), { target: { value: '0' } })
    expect(lastDoc(onDoc).checks[0].flaky).toBeUndefined()
  })

  it('adds and removes checks', async () => {
    const onDoc = vi.fn()
    render(<Harness initial={'checks: []\n'} onDoc={onDoc} />)

    expect(screen.getByText('No checks.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add check' }))
    expect(lastDoc(onDoc).checks).toHaveLength(1)

    await userEvent.click(screen.getByLabelText('Remove check'))
    expect(lastDoc(onDoc).checks).toHaveLength(0)
  })
})
