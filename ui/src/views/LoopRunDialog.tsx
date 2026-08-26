// LoopRunDialog.tsx — Run an autonomous loop (alc loop) in the foreground.
//
// The loop wrapper repeats `alc cycle` until the loop stops, sleeping `interval`
// seconds between cycles. Pick the pause, optionally reset the stopped state
// first, and override the engine, then dispatch an exec and open the console.
import { useState } from 'react'
import { ApiError } from '../api/client'
import { useEngines } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { Dialog, DialogButton } from '../components/Dialog'
import { Checkbox, Field, NumberInput, Select } from '../components/fields'

export function LoopRunDialog({ name, onClose }: { name: string; onClose: () => void }) {
  const id = useProjectId()
  const start = useStartExec()
  const engines = useEngines(id).data ?? []

  const [interval, setInterval] = useState<number | ''>(0)
  const [reset, setReset] = useState(false)
  const [engine, setEngine] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    const args: Record<string, unknown> = { name, interval: interval === '' ? 0 : interval }
    if (reset) args.reset = true
    if (engine) args.engine = engine
    setSaving(true)
    setError(null)
    try {
      await start('loop', args)
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to start.')
      setSaving(false)
    }
  }

  const engineOptions = [
    { value: '', label: 'default' },
    ...engines.map((e) => ({ value: e.name, label: e.default ? `${e.name} (default)` : e.name })),
  ]

  return (
    <Dialog
      title={`Run loop · ${name}`}
      onClose={onClose}
      width={520}
      footer={
        <>
          <DialogButton tone="ghost" onClick={onClose}>
            Cancel
          </DialogButton>
          <DialogButton onClick={submit} disabled={saving}>
            Run
          </DialogButton>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Interval">
            <NumberInput value={interval} onChange={setInterval} placeholder="0" />
          </Field>
          <Field label="Engine">
            <Select value={engine} onChange={setEngine} options={engineOptions} />
          </Field>
        </div>

        <Checkbox checked={reset} onChange={setReset} label="Reset the loop's stopped state first" />

        {error && <p className="text-[length:var(--ui-text-label)] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
