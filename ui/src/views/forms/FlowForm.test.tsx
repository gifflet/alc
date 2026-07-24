import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { parseDocument } from 'yaml'
import { FlowForm } from './FlowForm'
import { renderControlledForm } from '../../test/utils'

const FLOW = `name: unship
description: Discover and prove a removed feature's symbols are gone.
# keep this note
custom_field: keep-me
stages:
  - name: map
    blueprint: discover
  - name: gate
    blueprint: chore
    verify_only: true
`

function lastRaw(onDoc: ReturnType<typeof vi.fn>): string {
  return onDoc.mock.calls.at(-1)![0] as string
}

function lastParsed(onDoc: ReturnType<typeof vi.fn>) {
  return parseDocument(lastRaw(onDoc)).toJSON()
}

function renderFlow(onDoc: ReturnType<typeof vi.fn>) {
  return renderControlledForm(FLOW, (value, onChange) => <FlowForm value={value} onChange={onChange} />, onDoc)
}

describe('FlowForm', () => {
  it('edits a field and preserves the comment and the unknown key', () => {
    const onDoc = vi.fn()
    renderFlow(onDoc)

    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Prove the feature is gone.' } })

    const raw = lastRaw(onDoc)
    expect(raw).toContain('# keep this note')
    expect(raw).toContain('custom_field: keep-me')
    expect(lastParsed(onDoc).description).toBe('Prove the feature is gone.')
  })

  it('materializes derive_checks only on the verify_only stage, and drops it when turned off', async () => {
    const onDoc = vi.fn()
    renderFlow(onDoc)

    await userEvent.click(screen.getByLabelText("Derive checks from an earlier stage's report"))
    fireEvent.change(screen.getByLabelText('From stage'), { target: { value: 'map' } })
    fireEvent.change(screen.getByLabelText('Field'), { target: { value: 'removed_symbols' } })
    fireEvent.change(screen.getByLabelText('Shell template'), { target: { value: '! grep -rn {value} src/' } })

    let stages = lastParsed(onDoc).stages
    expect(stages[0].derive_checks).toBeUndefined()
    expect(stages[1].derive_checks).toEqual({
      from_stage: 'map',
      field: 'removed_symbols',
      shell_template: '! grep -rn {value} src/',
    })

    await userEvent.click(screen.getByLabelText("Derive checks from an earlier stage's report"))
    stages = lastParsed(onDoc).stages
    expect(stages[1].derive_checks).toBeUndefined()
  })

  it('forces a stage back to a blueprint ref when verify_only is enabled', async () => {
    const onDoc = vi.fn()
    renderFlow(onDoc)

    const refKindSelects = screen.getAllByLabelText('Stage ref kind')
    fireEvent.change(refKindSelects[0], { target: { value: 'specialist' } })
    expect(lastParsed(onDoc).stages[0].specialist).toBeDefined()

    const verifyOnlyCheckboxes = screen.getAllByLabelText(
      'Verify only (run checks as a pure gate, no engine turn)',
    )
    await userEvent.click(verifyOnlyCheckboxes[0])

    const stage0 = lastParsed(onDoc).stages[0]
    expect(stage0.verify_only).toBe(true)
    expect(stage0.blueprint).toBeDefined()
    expect(stage0.specialist).toBeUndefined()
  })
})
