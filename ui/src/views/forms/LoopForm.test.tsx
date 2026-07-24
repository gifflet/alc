import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { parseDocument } from 'yaml'
import { LoopForm } from './LoopForm'
import { renderControlledForm } from '../../test/utils'

const LOOP = `name: deliver
# keep this note
custom_field: keep-me
replenish:
  kind: conduct
  task: "Ship the next highest-impact item."
stop:
  max_cycles: 20
  on_no_new_work: true
`

function lastRaw(onDoc: ReturnType<typeof vi.fn>): string {
  return onDoc.mock.calls.at(-1)![0] as string
}

function lastParsed(onDoc: ReturnType<typeof vi.fn>) {
  return parseDocument(lastRaw(onDoc)).toJSON()
}

function renderLoop(onDoc: ReturnType<typeof vi.fn>) {
  return renderControlledForm(LOOP, (value, onChange) => <LoopForm value={value} onChange={onChange} />, onDoc)
}

describe('LoopForm', () => {
  it('edits a field and preserves the comment and the unknown key', () => {
    const onDoc = vi.fn()
    renderLoop(onDoc)

    fireEvent.change(screen.getByLabelText('Max cycles'), { target: { value: '30' } })

    const raw = lastRaw(onDoc)
    expect(raw).toContain('# keep this note')
    expect(raw).toContain('custom_field: keep-me')
    expect(lastParsed(onDoc).stop.max_cycles).toBe(30)
  })

  it('the replenish kind Select includes and persists signals and regression', () => {
    const onDoc = vi.fn()
    renderLoop(onDoc)

    const kindSelect = screen.getByLabelText('Kind') as HTMLSelectElement
    const optionValues = Array.from(kindSelect.options).map((o) => o.value)
    expect(optionValues).toEqual(expect.arrayContaining(['signals', 'regression']))

    fireEvent.change(kindSelect, { target: { value: 'signals' } })
    fireEvent.change(screen.getByLabelText('Ref'), { target: { value: 'ship' } })
    let replenish = lastParsed(onDoc).replenish
    expect(replenish).toEqual({ kind: 'signals', ref: 'ship', task: 'Ship the next highest-impact item.' })

    fireEvent.change(kindSelect, { target: { value: 'regression' } })
    replenish = lastParsed(onDoc).replenish
    expect(replenish.kind).toBe('regression')
    expect(replenish.ref).toBe('ship')
  })

  it('turns the replenish step off (Mode B, drain-only) and back on', async () => {
    const onDoc = vi.fn()
    renderLoop(onDoc)

    // Two "Enabled" toggles exist (replenish, budget) — the replenish one is first.
    const replenishToggle = screen.getAllByLabelText('Enabled')[0]
    await userEvent.click(replenishToggle)
    expect(lastParsed(onDoc).replenish).toBeUndefined()
    expect(screen.getByText('Drain-only loop (Mode B) — no replenish step.')).toBeInTheDocument()

    await userEvent.click(screen.getAllByLabelText('Enabled')[0])
    expect(lastParsed(onDoc).replenish).toEqual({ kind: 'conduct', task: '' })
  })

  it('adds and removes a cumulative usage budget', async () => {
    const onDoc = vi.fn()
    renderLoop(onDoc)

    expect(screen.queryByLabelText('Unit')).not.toBeInTheDocument()
    const budgetToggles = screen.getAllByLabelText('Enabled')
    await userEvent.click(budgetToggles[1])

    let stop = lastParsed(onDoc).stop
    expect(stop.budget).toEqual({ unit: 'usd', max: 1 })

    fireEvent.change(screen.getByLabelText('Unit'), { target: { value: 'tokens' } })
    stop = lastParsed(onDoc).stop
    expect(stop.budget.unit).toBe('tokens')

    fireEvent.change(screen.getByLabelText('Max'), { target: { value: '50' } })
    stop = lastParsed(onDoc).stop
    expect(stop.budget.max).toBe(50)
  })
})
