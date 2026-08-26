// ProjectSwitcher.tsx — Cmd+P: get to another project without leaving the keyboard.
//
// Search-first, not a form. The old flow was a modal that asked you to paste an
// absolute path before it would do anything, which is the right shape for
// registering a project and the wrong one for the thing done far more often —
// moving between projects already registered.
//
// Typing filters; Enter opens. Registering is still reachable, but it is the
// last row rather than the first thing in your way.
import { useEffect, useMemo, useRef, useState } from 'react'
import { FolderPlus, Search } from 'lucide-react'
import type { ProjectSummary } from '../api/types'
import { StatusDot } from './StatusDot'

/** Substring match over name and path, case-insensitive. Deliberately not fuzzy:
 *  a registry holds a handful of projects, and exact-substring keeps the result
 *  order predictable enough to hit Enter without reading. */
export function filterProjects(projects: ProjectSummary[], query: string): ProjectSummary[] {
  const q = query.trim().toLowerCase()
  if (!q) return projects
  return projects.filter(
    (p) => p.name.toLowerCase().includes(q) || p.path.toLowerCase().includes(q),
  )
}

export function ProjectSwitcher({
  projects,
  activeId,
  onSelect,
  onRegister,
  onClose,
}: {
  projects: ProjectSummary[]
  activeId: string | null
  onSelect: (id: string) => void
  onRegister: () => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const restoreRef = useRef<HTMLElement | null>(null)

  const matches = useMemo(() => filterProjects(projects, query), [projects, query])
  // The register row is the last stop, so arrowing past the projects lands on it.
  const rowCount = matches.length + 1

  useEffect(() => {
    restoreRef.current = document.activeElement as HTMLElement | null
    inputRef.current?.focus()
    return () => restoreRef.current?.focus?.()
  }, [])

  useEffect(() => setCursor(0), [query])

  const activate = (index: number) => {
    if (index === matches.length) {
      onRegister()
      return
    }
    const project = matches[index]
    if (project) onSelect(project.id)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCursor((c) => (c + 1) % rowCount)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCursor((c) => (c - 1 + rowCount) % rowCount)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      activate(cursor)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[12vh]"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Switch project"
        className="w-full max-w-lg overflow-hidden rounded-panel border border-border bg-panel shadow-[var(--elev-3)]"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="flex items-center gap-2.5 border-b border-border px-3.5">
          <Search className="h-4 w-4 shrink-0 text-faint" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search projects by name or path…"
            aria-label="Search projects"
            className="h-11 w-full bg-transparent text-[length:var(--ui-text-body)] text-primary outline-none placeholder:text-faint"
          />
        </div>

        <ul className="max-h-[46vh] overflow-y-auto py-1">
          {matches.map((p, i) => {
            const selected = i === cursor
            return (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => activate(i)}
                  onMouseEnter={() => setCursor(i)}
                  aria-current={p.id === activeId ? 'true' : undefined}
                  className={
                    'flex min-h-[var(--ui-row-h)] w-full items-center gap-2.5 px-3.5 text-left ' +
                    (selected ? 'bg-hover' : '')
                  }
                >
                  {/* An unavailable project stays listed and says so, rather than
                      vanishing — a directory that moved is a thing to fix, not a
                      project that never existed. */}
                  <StatusDot tone={p.available ? 'live' : 'error'} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[length:var(--ui-text-body)] text-primary">
                      {p.name}
                      {p.id === activeId && (
                        <span className="ml-2 text-[length:var(--ui-text-label)] text-faint">
                          current
                        </span>
                      )}
                    </span>
                    <span className="block truncate font-mono text-[length:var(--ui-text-label)] text-faint">
                      {p.path}
                    </span>
                  </span>
                  {!p.available && (
                    <span className="shrink-0 text-[length:var(--ui-text-label)] text-error">
                      unavailable
                    </span>
                  )}
                </button>
              </li>
            )
          })}

          {matches.length === 0 && query.trim() !== '' && (
            <li className="px-3.5 py-3 text-[length:var(--ui-text-body)] text-faint">
              No project matches “{query.trim()}”.
            </li>
          )}

          <li>
            <button
              type="button"
              onClick={() => activate(matches.length)}
              onMouseEnter={() => setCursor(matches.length)}
              className={
                'flex min-h-[var(--ui-row-h)] w-full items-center gap-2.5 border-t border-border/15 px-3.5 text-left ' +
                (cursor === matches.length ? 'bg-hover' : '')
              }
            >
              <FolderPlus className="h-3.5 w-3.5 shrink-0 text-faint" />
              <span className="text-[length:var(--ui-text-body)] text-primary">
                Register a project…
              </span>
            </button>
          </li>
        </ul>
      </div>
    </div>
  )
}
