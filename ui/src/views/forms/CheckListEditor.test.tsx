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

  it('saves a metric carrying shell syntax as a string, not a split argv (finding 48)', () => {
    const onDoc = vi.fn()
    render(
      <Harness
        initial={'checks:\n  - name: lines\n    metric: ["true"]\n    direction: lower_is_better\n    tolerance_pct: 0\n'}
        onDoc={onDoc}
      />
    )
    fireEvent.change(screen.getByLabelText('Check value'), {
      target: { value: "git ls-files ui/src | xargs wc -l | tail -1 | awk '{print $1}'" },
    })
    const parsed = lastDoc(onDoc)
    // The whole pipeline survives as one shell string — argv-splitting it
    // would hand `|` and `xargs` to git as literal arguments.
    expect(parsed.checks[0].metric).toBe("git ls-files ui/src | xargs wc -l | tail -1 | awk '{print $1}'")
    expect(parsed.checks[0].direction).toBe('lower_is_better')
  })

  it('turns a command carrying shell syntax into a shell one-liner, and the mode chip follows', () => {
    const onDoc = vi.fn()
    render(<Harness initial={'checks:\n  - name: smoke\n    command: ["true"]\n'} onDoc={onDoc} />)
    fireEvent.change(screen.getByLabelText('Check value'), {
      target: { value: 'npm test && npm run build' },
    })
    const parsed = lastDoc(onDoc)
    expect(parsed.checks[0].shell).toBe('npm test && npm run build')
    expect(parsed.checks[0].command).toBeUndefined()
    // The saved shape is what the row re-reads — the flip is the feedback.
    expect((screen.getByLabelText('Check mode') as HTMLSelectElement).value).toBe('shell')
  })

  it('round-trips an existing string metric without argv-splitting it', () => {
    const onDoc = vi.fn()
    render(
      <Harness
        initial={'checks:\n  - name: lines\n    metric: git ls-files | wc -l\n    direction: lower_is_better\n    tolerance_pct: 0\n'}
        onDoc={onDoc}
      />
    )
    // Touch an unrelated field so the row re-saves in full.
    fireEvent.change(screen.getByLabelText('Tolerance percent'), { target: { value: '2' } })
    const parsed = lastDoc(onDoc)
    expect(parsed.checks[0].metric).toBe('git ls-files | wc -l')
    expect(parsed.checks[0].tolerance_pct).toBe(2)
  })
})
