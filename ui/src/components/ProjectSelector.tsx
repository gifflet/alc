// ProjectSelector.tsx — Register / open / deregister projects (overlay panel).
import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderPlus, FolderSearch, Trash2, X } from 'lucide-react'
import { ApiError, api } from '../api/client'
import { useProjects } from '../api/hooks'
import { keys } from '../api/keys'
import { CloneForm } from './CloneForm'
import { NewProjectForm } from './NewProjectForm'
import { DirectoryBrowser } from './DirectoryBrowser'
import { ConfirmDialog } from './Dialog'
import { EmptyState } from './EmptyState'
import { useWs } from '../ws/WsProvider'
import { StatusDot } from './StatusDot'
import { ActionButton } from './ActionButton'

export function ProjectSelector({
  activeId,
  onClose,
  onSelect,
}: {
  activeId: string | null
  onClose: () => void
  onSelect: (id: string) => void
}) {
  const queryClient = useQueryClient()
  const { client } = useWs()
  const { data: projects, isLoading } = useProjects()
  const [path, setPath] = useState('')
  const [browsing, setBrowsing] = useState(false)
  const [removing, setRemoving] = useState<string | null>(null)
  const [mode, setMode] = useState<'register' | 'clone' | 'new'>('register')
  const [adoptExec, setAdoptExec] = useState<string | null>(null)
  const [adoptPath, setAdoptPath] = useState<string | null>(null)
  const [adoptError, setAdoptError] = useState<string | null>(null)
  const [name, setName] = useState('')

  const invalidate = () => queryClient.invalidateQueries({ queryKey: keys.projects() })

  const adopt = useMutation({
    mutationFn: (target: string) => api.adoptDirectory(target),
    onSuccess: (started) => {
      setAdoptExec(started.exec_id)
      setAdoptPath(started.destination)
      setAdoptError(null)
    },
    onError: (err) =>
      setAdoptError(err instanceof ApiError ? err.message : String(err)),
  })


  const add = useMutation({
    mutationFn: () => api.addProject(path.trim(), name.trim() || undefined),
    onSuccess: (project) => {
      setPath('')
      setName('')
      invalidate()
      onSelect(project.id)
    },
  })

  // `alc init` is a subprocess: the field can only be filled once it exits
  // clean, or the operator registers a directory that has no manifest yet.
  useEffect(() => {
    if (!adoptExec || !client) return
    const finish = (exitCode: number | null) => {
      setAdoptExec(null)
      if (exitCode === 0 && adoptPath) {
        setPath(adoptPath)
        // Asking to set ALC up here IS asking for the project. Filling the
        // field and stopping makes the operator hunt for a second button to
        // finish something they already asked for.
        add.mutate()
      } else {
        setAdoptError(`alc init exited with code ${exitCode}`)
      }
    }
    const off = client.on((msg) => {
      if (msg.type === 'exec_finished' && msg.exec_id === adoptExec) finish(msg.exit_code)
    })
    // The subscribe races the subprocess: a small scaffold exits in
    // milliseconds, so exec_finished can publish BEFORE this effect runs and
    // the completion is lost — the operator taps "Set up ALC here", the .alc/
    // appears on disk, and nothing on screen ever finishes. Ask once for the
    // current state; whichever side answers first wins, the loser no-ops on
    // the cleared adoptExec.
    void api.getExec(adoptExec).then((ex) => {
      if (ex.status !== 'running') finish(ex.exit_code ?? null)
    }).catch(() => {})
    return off
  }, [adoptExec, client, adoptPath, add])

  const remove = useMutation({
    mutationFn: (id: string) => api.removeProject(id),
    onSuccess: invalidate,
  })

  const addError =
    add.error instanceof ApiError
      ? add.error.message
      : add.error
        ? 'Failed to register project.'
        : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-label="Projects"
        className="flex max-h-[80vh] w-full max-w-[540px] flex-col rounded-[var(--radius-lg)] bg-panel shadow-[var(--elev-3)] ring-1 ring-border/50"
      >
        <header className="flex items-center justify-between border-b border-border px-3 py-2">
          <h2 className="text-[length:var(--ui-text-title)] font-medium text-primary">Projects</h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint hover:text-primary"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-auto">
          {isLoading ? (
            <p className="p-4 text-[length:var(--ui-text-body)] text-muted">Loading…</p>
          ) : projects && projects.length > 0 ? (
            projects.map((p) => (
              <div
                key={p.id}
                className={`flex h-[44px] min-w-0 items-center gap-2 border-b border-border/15 px-3 transition-colors duration-120 hover:bg-hover ${
                  p.id === activeId ? 'bg-hover' : ''
                }`}
              >
                <StatusDot tone={p.available ? 'live' : 'error'} title={p.available ? 'available' : 'unavailable'} />
                <button
                  type="button"
                  onClick={() => onSelect(p.id)}
                  className="flex min-w-0 flex-1 flex-col items-start text-left"
                >
                  <span className="w-full truncate text-[length:var(--ui-text-body)] text-primary">{p.name}</span>
                  <span className="w-full truncate font-mono text-[length:var(--ui-text-label)] text-faint">{p.path}</span>
                </button>
                <span className="shrink-0 tabular text-[length:var(--ui-text-label)] text-faint">{p.queue_pending} queued</span>
                <button
                  type="button"
                  aria-label={`Remove ${p.name}`}
                  onClick={() => setRemoving(p.id)}
                  className="flex h-[var(--ui-control-h)] w-[var(--ui-control-h)] shrink-0 items-center justify-center text-faint hover:text-error"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          ) : (
            <EmptyState icon={FolderPlus} message="No projects registered yet." />
          )}
        </div>

        <div className="flex gap-1 border-t border-border px-3 pt-2">
          {(['register', 'clone', 'new'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              aria-pressed={mode === m}
              className={`inline-flex min-h-[var(--ui-control-h)] items-center rounded-xs px-2.5 text-[length:var(--ui-text-body)] transition-colors duration-120 ${
                mode === m ? 'bg-hover text-primary' : 'text-faint hover:text-primary'
              }`}
            >
              {m === 'register' ? 'Register existing' : m === 'clone' ? 'Clone a repository' : 'New project'}
            </button>
          ))}
        </div>

        {mode === 'new' ? (
          <div className="p-3">
            <NewProjectForm
              onCreated={(createdPath) => {
                setPath(createdPath)
                setMode('register')
              }}
            />
          </div>
        ) : mode === 'clone' ? (
          <div className="p-3">
            <CloneForm
              onCloned={(clonedPath) => {
                // A finished clone is a directory the operator wants registered;
                // handing it to the same field means one path through the code.
                setPath(clonedPath)
                setMode('register')
              }}
            />
          </div>
        ) : (
        <form
          className="p-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (path.trim()) add.mutate()
          }}
        >
          <div className="flex flex-col gap-2">
            <div className="flex gap-2">
              <input
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="/absolute/path/to/project"
                spellCheck={false}
                aria-label="Project path"
                className="min-w-0 flex-1 rounded-panel border border-border bg-base min-h-[var(--ui-control-h)] px-2 font-mono text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
              />
              {/* The field stays for anyone who knows the path; browsing is for
                  everyone else, which is most of the time. */}
              <ActionButton
                onClick={() => setBrowsing((b) => !b)}
                aria-expanded={browsing}
                tone="ghost"
                size="md"
                className="shrink-0"
              >
                <FolderSearch className="h-3.5 w-3.5" />
                {browsing ? 'Hide' : 'Browse'}
              </ActionButton>
            </div>
            {browsing && (
              <DirectoryBrowser
                onPick={(picked) => {
                  setPath(picked)
                  setBrowsing(false)
                }}
                onAdopt={(target) => adopt.mutate(target)}
              />
            )}
            <div className="flex gap-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="name (optional)"
                className="flex-1 rounded-panel border border-border bg-base min-h-[var(--ui-control-h)] px-2 text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
              />
              <ActionButton
                type="submit"
                disabled={!path.trim() || add.isPending}
                tone="accent"
                size="md"
              >
                <FolderPlus className="h-3.5 w-3.5" />
                Register
              </ActionButton>
            </div>
            {adoptExec && (
              <p className="text-[length:var(--ui-text-label)] text-muted">
                Setting ALC up in {adoptPath}…
              </p>
            )}
            {adoptError && (
              <p className="text-[length:var(--ui-text-label)] text-error">{adoptError}</p>
            )}
            {addError && <p className="text-[length:var(--ui-text-label)] text-error">{addError}</p>}
          </div>
        </form>
        )}
      </div>

      {removing && (
        <ConfirmDialog
          title="Remove project"
          // The sentence ProjectUnavailable already uses, because it is the
          // question the operator actually has: does this delete my code?
          message={`Remove ${
            projects?.find((p) => p.id === removing)?.name ?? removing
          } from this control room? The files on disk are untouched — only ALC forgets about it.`}
          confirmLabel="Remove"
          tone="error"
          onConfirm={() => {
            remove.mutate(removing)
            setRemoving(null)
          }}
          onCancel={() => setRemoving(null)}
        />
      )}
    </div>
  )
}
