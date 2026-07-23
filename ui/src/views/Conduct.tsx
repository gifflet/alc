// Conduct.tsx — Dispatch the Conductor against a high-level goal.
//
// The Conductor plans the required flows and either runs them now or (with
// enqueue) writes queue tasks for `alc tick`; --parallel fans independent units
// out into isolated worktrees. Output streams to the console; enqueued tasks
// surface in the Queue live via WS.
import { useState } from 'react'
import { Wand2 } from 'lucide-react'
import { ApiError } from '../api/client'
import { useEngines } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { Checkbox, Field, Select, TextArea } from '../components/fields'

export function Conduct() {
  const id = useProjectId()
  const start = useStartExec()
  const engines = useEngines(id).data ?? []
  const tiers = Array.from(new Set(engines.flatMap((e) => Object.keys(e.tiers))))

  const [goal, setGoal] = useState('')
  const [engine, setEngine] = useState('')
  const [tier, setTier] = useState('')
  const [parallel, setParallel] = useState(false)
  const [enqueue, setEnqueue] = useState(false)
  const [strictStage, setStrictStage] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    const args: Record<string, unknown> = { goal }
    if (engine) args.engine = engine
    if (tier) args.tier = tier
    if (parallel) args.parallel = true
    if (enqueue) args.enqueue = true
    if (strictStage) args['strict-stage'] = true
    setSaving(true)
    setError(null)
    try {
      await start('conduct', args)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to start.')
    } finally {
      setSaving(false)
    }
  }

  const engineOptions = [
    { value: '', label: 'default' },
    ...engines.map((e) => ({ value: e.name, label: e.default ? `${e.name} (default)` : e.name })),
  ]

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="flex shrink-0 items-center gap-2 border-b border-border bg-panel px-4 py-2">
        <Wand2 className="h-3.5 w-3.5 text-muted" strokeWidth={1.75} />
        <h2 className="text-[12px] font-medium text-primary">Conduct</h2>
      </div>

      <div className="mx-auto flex w-full max-w-[640px] flex-col gap-4 p-4">
        <p className="text-[12px] text-muted">
          Describe a goal — the Conductor plans the flows and runs them now, or enqueues them for a
          drain.
        </p>

        <Field label="Goal">
          <TextArea value={goal} onChange={setGoal} rows={6} placeholder="e.g. add and wire a settings page" />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Engine">
            <Select value={engine} onChange={setEngine} options={engineOptions} />
          </Field>
          <Field label="Plan tier">
            <Select
              value={tier}
              onChange={setTier}
              options={[{ value: '', label: 'default' }, ...tiers.map((t) => ({ value: t, label: t }))]}
            />
          </Field>
        </div>

        <div className="flex flex-col gap-2 rounded-panel border border-border bg-base p-3">
          <Checkbox checked={parallel} onChange={setParallel} label="Run independent units in parallel (isolated worktrees)" />
          <Checkbox checked={enqueue} onChange={setEnqueue} label="Enqueue tasks instead of running now" />
          <Checkbox
            checked={strictStage}
            onChange={setStrictStage}
            label="Enforce the declared stage's mix (--strict-stage)"
          />
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={submit}
            disabled={!goal.trim() || saving}
            className="flex items-center gap-1.5 rounded-panel border border-accent/60 bg-accent/10 px-3 py-1.5 text-[12px] text-accent transition-colors duration-120 hover:bg-accent/20 disabled:opacity-40"
          >
            <Wand2 className="h-3.5 w-3.5" />
            Conduct goal
          </button>
          {error && <span className="text-[11px] text-error">{error}</span>}
        </div>
      </div>
    </div>
  )
}
