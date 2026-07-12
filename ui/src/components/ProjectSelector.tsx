// ProjectSelector.tsx — Register / open / deregister projects (overlay panel).
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderPlus, Trash2, X } from 'lucide-react'
import { ApiError, api } from '../api/client'
import { useProjects } from '../api/hooks'
import { keys } from '../api/keys'
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
      <div className="flex max-h-[80vh] w-[540px] flex-col rounded-panel border border-border bg-panel shadow-lg">
        <header className="flex items-center justify-between border-b border-border px-3 py-2">
          <h2 className="text-[13px] font-medium text-primary">Projects</h2>
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
            <p className="p-4 text-[12px] text-muted">Loading…</p>
          ) : projects && projects.length > 0 ? (
            projects.map((p) => (
              <div
                key={p.id}
                className={`flex h-[44px] items-center gap-2 border-b border-border/60 px-3 transition-colors duration-120 hover:bg-hover ${
                  p.id === activeId ? 'bg-hover' : ''
                }`}
              >
                <StatusDot tone={p.available ? 'live' : 'error'} title={p.available ? 'available' : 'unavailable'} />
                <button
                  type="button"
                  onClick={() => onSelect(p.id)}
                  className="flex min-w-0 flex-1 flex-col items-start text-left"
                >
                  <span className="truncate text-[12px] text-primary">{p.name}</span>
                  <span className="truncate font-mono text-[11px] text-faint">{p.path}</span>
                </button>
                <span className="tabular text-[11px] text-faint">{p.queue_pending} queued</span>
                <button
                  type="button"
                  aria-label={`Remove ${p.name}`}
                  onClick={() => remove.mutate(p.id)}
                  className="flex h-6 w-6 items-center justify-center text-faint hover:text-error"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          ) : (
            <EmptyState icon={FolderPlus} message="No projects registered yet." />
          )}
        </div>

        <form
          className="border-t border-border p-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (path.trim()) add.mutate()
          }}
        >
          <div className="flex flex-col gap-2">
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="/absolute/path/to/project"
              spellCheck={false}
              className="rounded-panel border border-border bg-base px-2 py-1.5 font-mono text-[12px] text-primary outline-none focus:border-accent"
            />
            <div className="flex gap-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="name (optional)"
                className="flex-1 rounded-panel border border-border bg-base px-2 py-1.5 text-[12px] text-primary outline-none focus:border-accent"
              />
              <button
                type="submit"
                disabled={!path.trim() || add.isPending}
                className="flex items-center gap-1.5 rounded-panel border border-accent/60 bg-accent/10 px-3 py-1.5 text-[12px] text-accent transition-colors duration-120 hover:bg-accent/20 disabled:opacity-40"
              >
                <FolderPlus className="h-3.5 w-3.5" />
                Register
              </button>
            </div>
            {addError && <p className="text-[11px] text-error">{addError}</p>}
          </div>
        </form>
      </div>
    </div>
  )
}
