// RunConfigs.tsx — Saved, named run presets: list + run selector + editor.
//
// Each config is a {command, args} preset. A row runs it (via useStartExec, the
// same dispatch the dialogs use, reusing POST /exec), edits it, or deletes it.
// The header carries a compact IntelliJ-style selector that runs a picked config.
import { useState } from 'react'
import { Pencil, Play, Plus, SlidersHorizontal, Trash2 } from 'lucide-react'
import { useDeleteRunConfig, useRunConfigs } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { ConfirmDialog } from '../components/Dialog'
import { EmptyState } from '../components/EmptyState'
import { Loading, Pill } from '../components/primitives'
import { RunConfigForm } from './RunConfigForm'
import type { RunConfig } from '../api/types'
import { ActionButton } from '../components/ActionButton'

/** The compact run selector: pick a saved config and run it. */
function RunSelector({ configs }: { configs: RunConfig[] }) {
  const start = useStartExec()
  const [selected, setSelected] = useState('')

  const run = () => {
    const cfg = configs.find((c) => c.name === selected)
    if (cfg) void start(cfg.command, cfg.args).catch(() => {})
  }

  return (
    <div className="flex items-center gap-1.5">
      <select
        aria-label="Run configuration"
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        className="rounded-panel border border-border bg-base px-2 py-1 text-[length:var(--ui-text-label)] text-primary outline-none focus:border-accent"
      >
        <option value="">Select a configuration…</option>
        {configs.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name}
          </option>
        ))}
      </select>
      <ActionButton
        aria-label="Run selected configuration"
        onClick={run}
        disabled={!selected}
        tone="live"
        size="sm"
      >
        <Play className="h-3 w-3" />
        Run
      </ActionButton>
    </div>
  )
}

function ConfigRow({ config, onEdit, onDelete }: {
  config: RunConfig
  onEdit: (c: RunConfig) => void
  onDelete: (name: string) => void
}) {
  const start = useStartExec()
  return (
    <div className="group flex h-[var(--ui-row-h)] w-full items-center gap-2 border-b border-border/15 px-3 text-[length:var(--ui-text-body)] hover:bg-hover">
      <span className="min-w-0 flex-1 truncate text-muted">{config.name}</span>
      <Pill tone="accent">{config.command}</Pill>
      <button
        type="button"
        aria-label={`Run ${config.name}`}
        onClick={() => void start(config.command, config.args).catch(() => {})}
        className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint transition-colors duration-120 hover:text-live"
      >
        <Play className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        aria-label={`Edit ${config.name}`}
        onClick={() => onEdit(config)}
        className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint alc-reveal hover:text-primary"
      >
        <Pencil className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        aria-label={`Delete ${config.name}`}
        onClick={() => onDelete(config.name)}
        className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint alc-reveal hover:text-error"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

export function RunConfigs() {
  const id = useProjectId()
  const { data, isLoading } = useRunConfigs(id)
  const del = useDeleteRunConfig(id)
  const [editing, setEditing] = useState<RunConfig | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  if (isLoading) return <Loading />
  const configs = data?.configs ?? []

  const confirmDelete = () => {
    if (!deleting) return
    del.mutate(deleting, { onSuccess: () => setDeleting(null) })
  }

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-panel px-4 py-2">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-3.5 w-3.5 text-muted" strokeWidth={1.75} />
          <h2 className="text-[length:var(--ui-text-body)] font-medium text-primary">Run Configurations</h2>
        </div>
        <div className="flex items-center gap-2">
          {configs.length > 0 && <RunSelector configs={configs} />}
          <ActionButton
            onClick={() => setCreating(true)}
            tone="accent"
            size="sm"
          >
            <Plus className="h-3 w-3" />
            New configuration
          </ActionButton>
        </div>
      </div>

      {configs.length === 0 ? (
        <EmptyState
          icon={SlidersHorizontal}
          message="No run configurations yet — create one to re-run a command without a dialog."
        />
      ) : (
        <div className="flex flex-col">
          {configs.map((c) => (
            <ConfigRow key={c.name} config={c} onEdit={setEditing} onDelete={setDeleting} />
          ))}
        </div>
      )}

      {creating && <RunConfigForm onClose={() => setCreating(false)} />}
      {editing && <RunConfigForm existing={editing} onClose={() => setEditing(null)} />}
      {deleting && (
        <ConfirmDialog
          title="Delete run configuration"
          message={`Delete "${deleting}"? This cannot be undone.`}
          confirmLabel="Delete"
          onConfirm={confirmDelete}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  )
}
