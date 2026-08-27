// LoopRunDialog.tsx — Run an autonomous loop (alc loop) in the foreground.
//
// The loop wrapper repeats `alc cycle` until the loop stops, sleeping `interval`
// seconds between cycles. Pick the pause, optionally reset the stopped state
// first, and override the engine, then dispatch an exec and open the console.
import { useState } from 'react'
import { ApiError } from '../api/client'
import { useCollectionItem, useEngines } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { Dialog, DialogButton } from '../components/Dialog'
import { Checkbox, Field, NumberInput, Select } from '../components/fields'

/** What this loop will spend, read from the loop's own file.
 *
 *  `max_cycles` is mandatory and validated `> 0` by the model, so every loop has
 *  a hard backstop — but the operator pressing Run cannot see the number unless
 *  we show it. Budget is optional; say so only when it is actually set. */
export function loopCeiling(parsed: unknown): { cycles: number | null; budget: string | null } {
  const stop = (parsed as { stop?: { max_cycles?: unknown; budget?: { unit?: unknown; max?: unknown } } })?.stop
  const cycles = typeof stop?.max_cycles === 'number' ? stop.max_cycles : null
  const budget =
    stop?.budget && typeof stop.budget.max === 'number'
      ? `${stop.budget.max} ${String(stop.budget.unit ?? 'usd')}`
      : null
  return { cycles, budget }
}

export function LoopRunDialog({ name, onClose }: { name: string; onClose: () => void }) {
  const id = useProjectId()
  const start = useStartExec()
  const engines = useEngines(id).data ?? []
  const { cycles, budget } = loopCeiling(useCollectionItem(id, 'loops', name).data?.parsed)

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
          <Field label="Interval" hint="Seconds between cycles. 0 runs them back to back.">
            <NumberInput value={interval} onChange={setInterval} placeholder="0" />
          </Field>
          <Field label="Engine">
            <Select value={engine} onChange={setEngine} options={engineOptions} />
          </Field>
        </div>

        <Checkbox checked={reset} onChange={setReset} label="Reset the loop's stopped state first" />

        {cycles !== null && (
          <p className="text-[length:var(--ui-text-label)] text-faint">
            Runs unattended for up to <span className="text-primary">{cycles} cycles</span>, one engine turn
            each{budget ? <>, or until it has spent <span className="text-primary">{budget}</span></> : null}. It
            also stops early when there is no new work.
          </p>
        )}

        {error && <p className="text-[length:var(--ui-text-label)] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
