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

  it('authors the service block from Start, revealing health and timeout (finding 51)', () => {
    const onDoc = vi.fn()
    renderManifest(onDoc)
    // Health/timeout hide until a start command exists — a service block
    // without `start` would not validate.
    expect(screen.queryByLabelText('Health path')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Start'), {
      target: { value: 'python3 -m http.server "$PORT"' },
    })
    expect(lastParsed(onDoc).service).toEqual({ start: 'python3 -m http.server "$PORT"' })
  })

  it('clears the whole service block when Start is emptied', () => {
    const onDoc = vi.fn()
    const withService = MANIFEST + 'service:\n  start: npm run dev\n  health: /up\n  ready_timeout_s: 10\n'
    renderControlledForm(withService, (value, onChange) => <ManifestForm value={value} onChange={onChange} />, onDoc)
    expect((screen.getByLabelText('Health path') as HTMLInputElement).value).toBe('/up')
    fireEvent.change(screen.getByLabelText('Start'), { target: { value: '' } })
    expect('service' in lastParsed(onDoc)).toBe(false)
    // Everything else survives the deletion.
    expect(lastParsed(onDoc).custom_field).toBe('keep-me')
  })

  it('drops an emptied health back to the model default instead of writing an empty string', () => {
    const onDoc = vi.fn()
    const withService = MANIFEST + 'service:\n  start: npm run dev\n  health: /up\n'
    renderControlledForm(withService, (value, onChange) => <ManifestForm value={value} onChange={onChange} />, onDoc)
    fireEvent.change(screen.getByLabelText('Health path'), { target: { value: '' } })
    expect(lastParsed(onDoc).service).toEqual({ start: 'npm run dev' })
  })

  it('authors non-secret service env vars and a gitignored secrets file (round 21)', () => {
    const onDoc = vi.fn()
    const withService = MANIFEST + 'service:\n  start: npm run dev\n'
    renderControlledForm(withService, (value, onChange) => <ManifestForm value={value} onChange={onChange} />, onDoc)

    // Env editor appears once a start command exists.
    fireEvent.click(screen.getByRole('button', { name: /add variable/i }))
    // The seeded KEY row: rename it and give it a value.
    fireEvent.change(screen.getByLabelText('Env var name KEY'), { target: { value: 'MONGO_DB' } })
    fireEvent.change(screen.getByLabelText('Env var value MONGO_DB'), { target: { value: 'hub' } })
    fireEvent.change(screen.getByLabelText(/secrets file/i), { target: { value: '.env' } })

    const parsed = lastParsed(onDoc)
    expect(parsed.service.env).toEqual({ MONGO_DB: 'hub' })
    expect(parsed.service.env_file).toBe('.env')
  })

  it('drops the env map and env_file when emptied', () => {
    const onDoc = vi.fn()
    const withService =
      MANIFEST + 'service:\n  start: npm run dev\n  env:\n    MONGO_DB: hub\n  env_file: .env\n'
    renderControlledForm(withService, (value, onChange) => <ManifestForm value={value} onChange={onChange} />, onDoc)

    fireEvent.click(screen.getByRole('button', { name: /remove env var MONGO_DB/i }))
    fireEvent.change(screen.getByLabelText(/secrets file/i), { target: { value: '' } })

    const parsed = lastParsed(onDoc)
    expect(parsed.service.env).toBeUndefined()
    expect(parsed.service.env_file).toBeUndefined()
    // The rest of the service block survives.
    expect(parsed.service.start).toBe('npm run dev')
  })

  it('exposes the delivery provider only in pr mode and writes it (azure/github)', async () => {
    const onDoc = vi.fn()
    renderManifest(onDoc)
    // Not shown until mode is pr.
    expect(screen.queryByLabelText('Provider')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'pr' } })
    // Now visible; choosing Azure writes delivery.provider.
    fireEvent.change(await screen.findByLabelText('Provider'), { target: { value: 'azure' } })
    expect(lastParsed(onDoc).delivery.provider).toBe('azure')
  })

  it('drops the provider key when set back to auto (auto is the default)', () => {
    const onDoc = vi.fn()
    const withPr = MANIFEST + 'delivery:\n  mode: pr\n  provider: azure\n'
    renderControlledForm(withPr, (value, onChange) => <ManifestForm value={value} onChange={onChange} />, onDoc)
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'auto' } })
    expect('provider' in (lastParsed(onDoc).delivery ?? {})).toBe(false)
  })

  it('exposes the delivery secrets-file only in pr mode and writes it', async () => {
    const onDoc = vi.fn()
    renderManifest(onDoc)
    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'pr' } })
    fireEvent.change(await screen.findByLabelText(/secrets file/i), { target: { value: '.env' } })
    expect(lastParsed(onDoc).delivery.env_file).toBe('.env')
    // Cleared -> the key is dropped.
    fireEvent.change(screen.getByLabelText(/secrets file/i), { target: { value: '' } })
    expect('env_file' in (lastParsed(onDoc).delivery ?? {})).toBe(false)
  })
})
