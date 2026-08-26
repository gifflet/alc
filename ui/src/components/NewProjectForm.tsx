// NewProjectForm.tsx — Start a project that does not exist yet.
//
// Creates the directory on the host and scaffolds an Operator Layer in it with
// `alc init`, which detects the stack and writes real checks. The output is
// followed rather than awaited, the same way a clone is: init prints what it
// found, and that is worth reading.
import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { FolderSearch, Loader2, Sparkles } from 'lucide-react'
import { ApiError, api } from '../api/client'
import { useWs } from '../ws/WsProvider'
import { DirectoryBrowser } from './DirectoryBrowser'

export function NewProjectForm({ onCreated }: { onCreated: (path: string) => void }) {
  const [parent, setParent] = useState('')
  const [name, setName] = useState('')
  const [withGit, setWithGit] = useState(true)
  const [browsing, setBrowsing] = useState(false)
  const [execId, setExecId] = useState<string | null>(null)
  const [destination, setDestination] = useState<string | null>(null)
  const [lines, setLines] = useState<string[]>([])
  const [failed, setFailed] = useState<string | null>(null)
  const { client } = useWs()

  const start = useMutation({
    mutationFn: () => api.newProject(parent.trim(), name.trim(), withGit),
    onSuccess: (started) => {
      setExecId(started.exec_id)
      setDestination(started.destination)
      setLines([])
      setFailed(null)
    },
  })

  useEffect(() => {
    if (!execId || !client) return
    return client.on((msg) => {
      if (msg.type === 'exec_output' && msg.exec_id === execId) {
        setLines((current) => [...current.slice(-40), msg.line])
      } else if (msg.type === 'exec_finished' && msg.exec_id === execId) {
        setExecId(null)
        if (msg.exit_code === 0 && destination) onCreated(destination)
        else setFailed(`alc init exited with code ${msg.exit_code}`)
      }
    })
  }, [execId, client, destination, onCreated])

  const startError =
    start.error instanceof ApiError ? start.error.message : start.error ? String(start.error) : null
  const busy = start.isPending || execId !== null

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (parent.trim() && name.trim() && !busy) start.mutate()
      }}
    >
      <div className="flex gap-2">
        <input
          value={parent}
          onChange={(e) => setParent(e.target.value)}
          placeholder="create inside which directory?"
          aria-label="Parent directory for the new project"
          spellCheck={false}
          disabled={busy}
          className="min-w-0 flex-1 rounded-panel border border-border bg-base min-h-[var(--ui-control-h)] px-2 font-mono text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent disabled:opacity-50"
        />
        <button
          type="button"
          onClick={() => setBrowsing((b) => !b)}
          disabled={busy}
          aria-expanded={browsing}
          className="flex shrink-0 items-center gap-1.5 rounded-panel border border-border min-h-[var(--ui-control-h)] px-2.5 text-[length:var(--ui-text-body)] text-primary hover:bg-hover disabled:opacity-50"
        >
          <FolderSearch className="h-3.5 w-3.5" />
          {browsing ? 'Hide' : 'Browse'}
        </button>
      </div>

      {browsing && (
        <DirectoryBrowser
          onPick={(picked) => {
            setParent(picked)
            setBrowsing(false)
          }}
        />
      )}

      <div className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="project name"
          aria-label="New project name"
          disabled={busy}
          className="min-w-0 flex-1 rounded-panel border border-border bg-base min-h-[var(--ui-control-h)] px-2 text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!parent.trim() || !name.trim() || busy}
          className="flex shrink-0 items-center gap-1.5 rounded-panel border border-accent/60 bg-accent/10 min-h-[var(--ui-control-h)] px-3 text-[length:var(--ui-text-body)] text-accent hover:bg-accent/20 disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          {execId ? 'Creating…' : 'Create'}
        </button>
      </div>

      <label className="flex min-h-[var(--ui-control-h)] items-center gap-2 text-[length:var(--ui-text-label)] text-muted">
        <input
          type="checkbox"
          checked={withGit}
          onChange={(e) => setWithGit(e.target.checked)}
          disabled={busy}
          className="h-3.5 w-3.5 accent-[var(--color-accent)]"
        />
        {/* Named as the consequence, not the command: isolation, landing and the
            commit step all need a repository. */}
        Initialise a git repository — isolated runs and landing need one
      </label>

      {(startError || failed) && (
        <p className="text-[length:var(--ui-text-label)] text-error">{startError ?? failed}</p>
      )}

      {lines.length > 0 && (
        <pre className="max-h-32 overflow-y-auto rounded-panel border border-border bg-base p-2 font-mono text-[length:var(--ui-text-label)] text-muted">
          {lines.join('\n')}
        </pre>
      )}
    </form>
  )
}
