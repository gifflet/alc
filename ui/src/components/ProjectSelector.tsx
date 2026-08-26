// ProjectSelector.tsx — Register / open / deregister projects (overlay panel).
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderPlus, FolderSearch, Trash2, X } from 'lucide-react'
import { ApiError, api } from '../api/client'
import { useProjects } from '../api/hooks'
import { keys } from '../api/keys'
import { CloneForm } from './CloneForm'
import { NewProjectForm } from './NewProjectForm'
import { DirectoryBrowser } from './DirectoryBrowser'
import { EmptyState } from './EmptyState'
import { StatusDot } from './StatusDot'

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
  const { data: projects, isLoading } = useProjects()
  const [path, setPath] = useState('')
  const [browsing, setBrowsing] = useState(false)
  const [mode, setMode] = useState<'register' | 'clone' | 'new'>('register')
  const [name, setName] = useState('')

  const invalidate = () => queryClient.invalidateQueries({ queryKey: keys.projects() })

  const add = useMutation({
    mutationFn: () => api.addProject(path.trim(), name.trim() || undefined),
    onSuccess: (project) => {
      setPath('')
      setName('')
      invalidate()
      onSelect(project.id)
    },
  })

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
            className="flex h-6 w-6 items-center justify-center text-faint hover:text-primary"
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
                  onClick={() => remove.mutate(p.id)}
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
              <button
                type="button"
                onClick={() => setBrowsing((b) => !b)}
                aria-expanded={browsing}
                className="flex shrink-0 items-center gap-1.5 rounded-panel border border-border min-h-[var(--ui-control-h)] px-2.5 text-[length:var(--ui-text-body)] text-primary transition-colors duration-120 hover:bg-hover"
              >
                <FolderSearch className="h-3.5 w-3.5" />
                {browsing ? 'Hide' : 'Browse'}
              </button>
            </div>
            {browsing && (
              <DirectoryBrowser
                onPick={(picked) => {
                  setPath(picked)
                  setBrowsing(false)
                }}
              />
            )}
            <div className="flex gap-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="name (optional)"
                className="flex-1 rounded-panel border border-border bg-base min-h-[var(--ui-control-h)] px-2 text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
              />
              <button
                type="submit"
                disabled={!path.trim() || add.isPending}
                className="flex items-center gap-1.5 rounded-panel border border-accent/60 bg-accent/10 min-h-[var(--ui-control-h)] px-3 text-[length:var(--ui-text-body)] text-accent transition-colors duration-120 hover:bg-accent/20 disabled:opacity-40"
              >
                <FolderPlus className="h-3.5 w-3.5" />
                Register
              </button>
            </div>
            {addError && <p className="text-[length:var(--ui-text-label)] text-error">{addError}</p>}
          </div>
        </form>
        )}
      </div>
    </div>
  )
}
