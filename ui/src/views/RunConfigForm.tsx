// RunConfigForm.tsx — Create or edit a Run Configuration.
//
// The form is generic: pick a command from the schema (GET /api/commands) and
// the inputs are GENERATED from that command's spec — positionals and value
// flags become text fields (engine is a Select), bool flags become checkboxes.
// Saving calls the create/update API; the whitelist keeps a saved config runnable.
import { useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import { useCommands, useCreateRunConfig, useEngines, useUpdateRunConfig } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { Dialog, DialogButton } from '../components/Dialog'
import { Checkbox, Field, Select, TextInput } from '../components/fields'
import type { RunConfig } from '../api/types'

export function RunConfigForm({
  existing,
  onClose,
}: {
  existing?: RunConfig
  onClose: () => void
}) {
  const id = useProjectId()
  const schema = useCommands().data ?? {}
  const engines = useEngines(id).data ?? []
  const create = useCreateRunConfig(id)
  const update = useUpdateRunConfig(id)

  const editing = existing !== undefined
  const commandNames = Object.keys(schema)

  const [name, setName] = useState(existing?.name ?? '')
  const [picked, setPicked] = useState(existing?.command ?? '')
  const [args, setArgs] = useState<Record<string, unknown>>(() => ({ ...(existing?.args ?? {}) }))
  const [error, setError] = useState<string | null>(null)

  // The command whitelist loads async; default to its first entry until the user
  // picks one, so the generated fields appear as soon as the schema arrives.
  const command = picked || commandNames[0] || ''
  const spec = schema[command]

  const engineOptions = useMemo(
    () => [
      { value: '', label: 'default' },
      ...engines.map((e) => ({ value: e.name, label: e.default ? `${e.name} (default)` : e.name })),
    ],
    [engines],
  )

  const setArg = (key: string, value: unknown) => setArgs((prev) => ({ ...prev, [key]: value }))

  const pickCommand = (next: string) => {
    setPicked(next)
    // A command switch invalidates the previous command's args.
    setArgs({})
  }

  const save = () => {
    // Drop empty string/false args so a saved config carries only what it sets.
    const cleaned: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(args)) {
      if (value === '' || value === false || value == null) continue
      cleaned[key] = value
    }
    const cfg: RunConfig = { name: name.trim(), command, args: cleaned }
    const onSuccess = () => onClose()
    const onError = (e: unknown) =>
      setError(e instanceof ApiError ? e.message : 'Failed to save.')
    if (editing) {
      update.mutate({ name: existing.name, cfg }, { onSuccess, onError })
    } else {
      create.mutate(cfg, { onSuccess, onError })
    }
  }

  const saving = create.isPending || update.isPending
  const commandOptions = commandNames.map((c) => ({ value: c, label: c }))

  return (
    <Dialog
      title={editing ? `Edit run configuration · ${existing.name}` : 'New run configuration'}
      onClose={onClose}
      width={520}
      footer={
        <>
          <DialogButton tone="ghost" onClick={onClose}>
            Cancel
          </DialogButton>
          <DialogButton onClick={save} disabled={!name.trim() || !command || saving}>
            {editing ? 'Save' : 'Create'}
          </DialogButton>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Name">
          <TextInput value={name} onChange={setName} placeholder="e.g. ship chore" autoFocus />
        </Field>

        <Field label="Command">
          <Select value={command} onChange={pickCommand} options={commandOptions} />
        </Field>

        {spec && (
          <div className="flex flex-col gap-3 rounded-panel border border-border bg-base p-3">
            {[...spec.positionals, ...spec.opt_positionals, ...spec.value_flags].map((key) => (
              <Field key={key} label={key}>
                {key === 'engine' ? (
                  <Select
                    value={String(args[key] ?? '')}
                    onChange={(v) => setArg(key, v)}
                    options={engineOptions}
                  />
                ) : (
                  <TextInput
                    value={String(args[key] ?? '')}
                    onChange={(v) => setArg(key, v)}
                    placeholder={spec.positionals.includes(key) ? 'required' : 'optional'}
                  />
                )}
              </Field>
            ))}
            {spec.bool_flags.map((key) => (
              <Checkbox
                key={key}
                checked={Boolean(args[key])}
                onChange={(v) => setArg(key, v)}
                label={key}
              />
            ))}
            {spec.positionals.length === 0 &&
              spec.opt_positionals.length === 0 &&
              spec.value_flags.length === 0 &&
              spec.bool_flags.length === 0 && (
                <p className="text-[11px] text-faint">This command takes no arguments.</p>
              )}
          </div>
        )}

        {error && <p className="text-[11px] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
