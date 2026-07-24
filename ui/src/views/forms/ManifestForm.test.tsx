import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { parseDocument } from 'yaml'
import { ManifestForm } from './ManifestForm'
import { renderControlledForm } from '../../test/utils'

const MANIFEST = `version: 1
default_engine: mock
engines:
  mock:
    type: mock
compute_tiers:
  standard:
    mock: mock-model
# an operator note about this manifest
custom_field: keep-me
`

function lastRaw(onDoc: ReturnType<typeof vi.fn>): string {
  return onDoc.mock.calls.at(-1)![0] as string
}

function lastParsed(onDoc: ReturnType<typeof vi.fn>) {
  return parseDocument(lastRaw(onDoc)).toJSON()
}

function renderManifest(onDoc: ReturnType<typeof vi.fn>) {
  return renderControlledForm(MANIFEST, (value, onChange) => <ManifestForm value={value} onChange={onChange} />, onDoc)
}

describe('ManifestForm', () => {
  it('edits a new field and preserves the comment and the unknown key', () => {
    const onDoc = vi.fn()
    renderManifest(onDoc)

    fireEvent.change(screen.getByLabelText('Stage'), { target: { value: 'growth' } })

    const raw = lastRaw(onDoc)
    expect(raw).toContain('# an operator note about this manifest')
    expect(raw).toContain('custom_field: keep-me')
    expect(lastParsed(onDoc).stage).toBe('growth')
  })

  it('stores a notify command as an argv list and a notify URL as a plain string', () => {
    const onDoc = vi.fn()
    renderManifest(onDoc)

    fireEvent.change(screen.getByLabelText('On task failed mode'), { target: { value: 'command' } })
    fireEvent.change(screen.getByLabelText('On task failed value'), {
      target: { value: 'notify-slack.sh --loud' },
    })
    let notify = lastParsed(onDoc).notify
    expect(notify.on_task_failed).toEqual(['notify-slack.sh', '--loud'])

    fireEvent.change(screen.getByLabelText('On loop stopped mode'), { target: { value: 'url' } })
    fireEvent.change(screen.getByLabelText('On loop stopped value'), {
      target: { value: 'https://hooks.example.com/x' },
    })
    notify = lastParsed(onDoc).notify
    expect(notify.on_loop_stopped).toBe('https://hooks.example.com/x')
    // The command event set earlier is untouched by the second edit.
    expect(notify.on_task_failed).toEqual(['notify-slack.sh', '--loud'])

    fireEvent.change(screen.getByLabelText('On task failed mode'), { target: { value: 'none' } })
    expect(lastParsed(onDoc).notify.on_task_failed).toBeUndefined()
  })

  it('adds a named check set holding its own checks', async () => {
    const onDoc = vi.fn()
    renderManifest(onDoc)

    expect(screen.getByText('No check sets.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('New check set name'), { target: { value: 'fast' } })
    await userEvent.click(screen.getByRole('button', { name: 'Add set' }))

    let parsed = lastParsed(onDoc)
    expect(parsed.check_sets.fast).toEqual([{ name: 'check', command: ['true'] }])

    await userEvent.selectOptions(screen.getByLabelText('Check mode'), 'metric')
    parsed = lastParsed(onDoc)
    expect(parsed.check_sets.fast[0].metric).toEqual(['true'])
    expect(parsed.check_sets.fast[0].direction).toBe('lower_is_better')

    await userEvent.click(screen.getByLabelText('Remove set fast'))
    expect(lastParsed(onDoc).check_sets).toEqual({})
  })

  it('edits quarantined checks and delivery, keeping the document intact otherwise', () => {
    const onDoc = vi.fn()
    renderManifest(onDoc)

    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    fireEvent.change(screen.getByPlaceholderText('check name'), { target: { value: 'flaky-e2e' } })
    expect(lastParsed(onDoc).quarantined_checks).toEqual(['flaky-e2e'])

    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'pr' } })
    fireEvent.change(screen.getByLabelText('Remote'), { target: { value: 'upstream' } })
    fireEvent.change(screen.getByLabelText('Base'), { target: { value: 'develop' } })
    const delivery = lastParsed(onDoc).delivery
    expect(delivery).toEqual({ mode: 'pr', remote: 'upstream', base: 'develop' })

    const raw = lastRaw(onDoc)
    expect(raw).toContain('custom_field: keep-me')
  })

  it('edits the new metrics/artifacts/signals directories', () => {
    const onDoc = vi.fn()
    renderManifest(onDoc)

    fireEvent.change(screen.getByLabelText('Metrics dir'), { target: { value: '.alc/custom-metrics' } })
    fireEvent.change(screen.getByLabelText('Artifacts dir'), { target: { value: '.alc/custom-artifacts' } })
    fireEvent.change(screen.getByLabelText('Signals dir'), { target: { value: '.alc/custom-signals' } })

    const parsed = lastParsed(onDoc)
    expect(parsed.metrics_dir).toBe('.alc/custom-metrics')
    expect(parsed.artifacts_dir).toBe('.alc/custom-artifacts')
    expect(parsed.signals_dir).toBe('.alc/custom-signals')
  })
})
