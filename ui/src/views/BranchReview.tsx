// BranchReview.tsx — Read a branch's change, and send notes back as work.
//
// This is the human moment ALC is built around: it sits right before `alc land`.
// Notes never reach a running engine turn (there is no join point that accepts
// free text mid-turn) — they compose ONE queue task, verified by the Assurance
// Loop like any other unit. Recorded, replayable, Scorecard-visible.
import { useState } from 'react'
import { GitMerge, Send, X } from 'lucide-react'
import { useBranchDiff, useCollection, useLandBranches, useSubmitReview } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useNarrow } from '../app/useDensity'
import { DiffView } from '../components/DiffView'
import type { DraftComment } from '../components/DiffView'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/primitives'
import { anchorKey } from '../lib/diff'
import { ApiError } from '../api/client'
import { ActionButton } from '../components/ActionButton'

export function BranchReview({ branch }: { branch: string }) {
  const id = useProjectId()
  // On a phone the shell header already shows the branch; repeating it here
  // squeezed it to "alc/ru…" and stole room from the controls that matter.
  const narrow = useNarrow()
  const { data, isLoading, error } = useBranchDiff(id, branch)
  const submit = useSubmitReview(id)
  const land = useLandBranches(id)

  // Drafts live here, not on the server: nothing is written to the project until
  // the operator submits.
  const [comments, setComments] = useState<Record<string, DraftComment>>({})
  const [editing, setEditing] = useState<{ path: string; line: number } | null>(null)
  const [draftText, setDraftText] = useState('')
  const [result, setResult] = useState<string | null>(null)
  // The notes have to run AS something. QueueTask.unit_name() falls back to an
  // empty string when no unit is named, which the drain cannot dispatch — so the
  // operator picks the Flow, and Send stays disabled until one exists.
  const flows = useCollection(id, 'flows')
  const [unit, setUnit] = useState<string>('')
  const flowNames = (flows.data ?? []).map((f) => f.name)
  const chosen = unit || flowNames[0] || ''

  if (isLoading) return <Loading />
  if (error) {
    return (
      <EmptyState
        icon={X}
        message={error instanceof ApiError ? error.message : `Could not read the diff for ${branch}.`}
      />
    )
  }

  const count = Object.keys(comments).length

  const openEditor = (path: string, line: number) => {
    setEditing({ path, line })
    setDraftText(comments[anchorKey(path, line)]?.text ?? '')
  }

  const saveDraft = () => {
    if (!editing) return
    const key = anchorKey(editing.path, editing.line)
    const text = draftText.trim()
    setComments((prev) => {
      const next = { ...prev }
      if (text) next[key] = { path: editing.path, line: editing.line, text }
      else delete next[key] // clearing the box removes the note
      return next
    })
    setEditing(null)
    setDraftText('')
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex min-h-[var(--ui-control-h)] shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-panel px-[var(--ui-pad-x)] py-1">
        <span className="min-w-0 flex-1 truncate font-mono text-[length:var(--ui-text-body)] text-muted">
          {narrow ? null : branch}
          {data?.base && <span className="text-faint">{narrow ? `vs ${data.base}` : ` vs ${data.base}`}</span>}
        </span>
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--ui-text-label)] text-faint">
            {count === 0 ? 'no notes' : `${count} note${count === 1 ? '' : 's'}`}
          </span>
          <label className="flex items-center gap-1 text-[length:var(--ui-text-label)] text-faint">
            run as
            <select
              value={chosen}
              onChange={(e) => setUnit(e.target.value)}
              aria-label="Flow to run the notes as"
              className="min-h-[var(--ui-control-h)] rounded-panel border border-border bg-base px-1 text-[length:var(--ui-text-label)] text-primary outline-none focus:border-accent"
            >
              {flowNames.length === 0 && <option value="">no flows</option>}
              {flowNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <ActionButton
            disabled={count === 0 || !chosen || submit.isPending}
            onClick={() =>
              submit.mutate(
                { branch, comments: Object.values(comments), kind: 'flow', name: chosen },
                {
                  onSuccess: (r) => {
                    setResult(`Queued as ${r.stem} — ${r.comments} note(s).`)
                    setComments({})
                  },
                },
              )
            }
            tone="accent"
            size="sm"
          >
            <Send className="h-3.5 w-3.5" />
            Send notes
          </ActionButton>
          <ActionButton
            disabled={land.isPending}
            onClick={() => land.mutate({ branches: [branch] })}
            tone="ghost"
            size="sm"
          >
            <GitMerge className="h-3.5 w-3.5" />
            Land
          </ActionButton>
        </div>
      </header>

      {result && (
        <p className="shrink-0 border-b border-border bg-live/10 px-[var(--ui-pad-x)] py-1 text-[length:var(--ui-text-label)] text-live">
          {result}
        </p>
      )}
      {data?.truncated && (
        <p className="shrink-0 border-b border-border px-[var(--ui-pad-x)] py-1 text-[length:var(--ui-text-label)] text-warn">
          Diff truncated — showing the first part only.
        </p>
      )}

      <div className="min-h-0 flex-1">
        <DiffView
          diff={data?.diff ?? ''}
          comments={comments}
          onComment={openEditor}
          activeAnchor={editing ? anchorKey(editing.path, editing.line) : null}
        />
      </div>

      {editing && (
        <div className="shrink-0 border-t border-border bg-panel p-[var(--ui-pad-x)]">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[length:var(--ui-text-label)] text-faint">
              {anchorKey(editing.path, editing.line)}
            </span>
            <textarea
              autoFocus
              value={draftText}
              onChange={(e) => setDraftText(e.target.value)}
              aria-label={`Note on ${anchorKey(editing.path, editing.line)}`}
              rows={2}
              className="min-h-[var(--ui-control-h)] w-full resize-y rounded-panel border border-border bg-base px-2 py-1.5 text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
            />
          </label>
          <div className="mt-2 flex gap-2">
            <ActionButton
              onClick={saveDraft}
              tone="accent"
              size="sm"
            >
              Save note
            </ActionButton>
            <ActionButton
              onClick={() => {
                setEditing(null)
                setDraftText('')
              }}
              tone="ghost"
              size="sm"
            >
              Cancel
            </ActionButton>
          </div>
        </div>
      )}
    </div>
  )
}
