// SignalIngestDialog.tsx — Compose a Signal and ingest it (kind/source/title/body).
import { useState } from 'react'
import { Dialog, DialogButton } from '../components/Dialog'
import { Field, Select, TextArea, TextInput } from '../components/fields'
import type { SignalIngestPayload } from '../api/types'

const KIND_OPTIONS = [
  { value: 'error', label: 'error' },
  { value: 'feedback', label: 'feedback' },
  { value: 'issue', label: 'issue' },
  { value: 'review', label: 'review' },
]

export function SignalIngestDialog({
  onClose,
  onSubmit,
  saving,
  error,
}: {
  onClose: () => void
  onSubmit: (payload: SignalIngestPayload) => void
  saving: boolean
  error: string | null
}) {
  const [kind, setKind] = useState<SignalIngestPayload['kind']>('error')
  const [source, setSource] = useState('')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')

  const submit = () => onSubmit({ kind, source, title, body })

  const canSubmit = Boolean(source.trim() && title.trim())

  return (
    <Dialog
      title="Ingest signal"
      onClose={onClose}
      width={480}
      footer={
        <>
          <DialogButton tone="ghost" onClick={onClose}>
            Cancel
          </DialogButton>
          <DialogButton onClick={submit} disabled={!canSubmit || saving}>
            Ingest
          </DialogButton>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Kind">
            <Select
              value={kind}
              onChange={(v) => setKind(v as SignalIngestPayload['kind'])}
              options={KIND_OPTIONS}
            />
          </Field>
          <Field label="Source">
            <TextInput value={source} onChange={setSource} placeholder="sentry, github, operator…" mono />
          </Field>
        </div>

        <Field label="Title">
          <TextInput value={title} onChange={setTitle} placeholder="Short summary" />
        </Field>

        <Field label="Body">
          <TextArea value={body} onChange={setBody} rows={4} placeholder="Details (optional)…" />
        </Field>

        {error && <p className="text-[length:var(--ui-text-label)] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
