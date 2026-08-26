// DirectoryBrowser.tsx — Pick a directory on the server's machine instead of typing its path.
//
// Registering a project meant knowing an absolute path by heart, or leaving the
// browser to go find one. This walks the filesystem of the host running the
// server — which is the machine the project has to be on anyway.
//
// It lists directories only, and marks the ones that are already ALC projects
// or git repositories, because that is the whole question being answered: which
// of these folders is the one I want to work in?
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowUp, Check, FolderGit2, Folder, Home, Loader2 } from 'lucide-react'
import { api } from '../api/client'
import type { DirectoryListing } from '../api/types'

export function DirectoryBrowser({
  onPick,
  className = '',
}: {
  /** Called with the absolute path of the directory the operator settles on. */
  onPick: (path: string) => void
  className?: string
}) {
  // undefined means "wherever the server calls home" — the browser opens
  // somewhere useful without the caller having to know the host's layout.
  const [path, setPath] = useState<string | undefined>(undefined)
  const [showHidden, setShowHidden] = useState(false)

  const { data, isLoading, error } = useQuery<DirectoryListing>({
    queryKey: ['fs', 'browse', path ?? '~', showHidden],
    queryFn: () => api.browseDirectory(path, showHidden),
  })

  return (
    <div className={`flex flex-col overflow-hidden rounded-panel border border-border ${className}`}>
      <div className="flex items-center gap-1 border-b border-border bg-raised px-1.5 py-1">
        <button
          type="button"
          aria-label="Home directory"
          title="Home directory"
          onClick={() => setPath(undefined)}
          className="flex h-[var(--ui-control-h)] w-[var(--ui-control-h)] items-center justify-center rounded-xs text-faint hover:bg-hover hover:text-primary"
        >
          <Home className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Parent directory"
          title="Parent directory"
          disabled={!data?.parent}
          onClick={() => data?.parent && setPath(data.parent)}
          className="flex h-[var(--ui-control-h)] w-[var(--ui-control-h)] items-center justify-center rounded-xs text-faint hover:bg-hover hover:text-primary disabled:opacity-40 disabled:hover:bg-transparent"
        >
          <ArrowUp className="h-3.5 w-3.5" />
        </button>
        <span
          title={data?.path}
          className="min-w-0 flex-1 truncate px-1 font-mono text-[length:var(--ui-text-label)] text-muted"
          // dir=rtl keeps the END of a long path visible, which is the part that
          // says where you are; the start is almost always /Users/<name>/….
          dir="rtl"
        >
          {data?.path ?? '…'}
        </span>
        <label className="flex items-center gap-1.5 px-1 text-[length:var(--ui-text-label)] text-faint">
          <input
            type="checkbox"
            checked={showHidden}
            onChange={(e) => setShowHidden(e.target.checked)}
            className="h-3 w-3 accent-[var(--color-accent)]"
          />
          Hidden
        </label>
      </div>

      <div className="max-h-64 min-h-[8rem] overflow-y-auto">
        {isLoading && (
          <p className="flex items-center gap-2 px-3 py-3 text-[length:var(--ui-text-body)] text-faint">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Reading…
          </p>
        )}

        {error && (
          <p className="px-3 py-3 text-[length:var(--ui-text-body)] text-error">
            {error instanceof Error ? error.message : 'Could not read that directory.'}
          </p>
        )}

        {data && data.entries.length === 0 && !isLoading && (
          <p className="px-3 py-3 text-[length:var(--ui-text-body)] text-faint">
            No sub-directories here{showHidden ? '' : ' — try Hidden'}.
          </p>
        )}

        <ul>
          {data?.entries.map((entry) => (
            <li key={entry.path} className="flex items-center">
              <button
                type="button"
                onClick={() => setPath(entry.path)}
                className="flex min-h-[var(--ui-row-h)] min-w-0 flex-1 items-center gap-2 px-3 text-left hover:bg-hover"
              >
                {entry.is_git_repo ? (
                  <FolderGit2 className="h-3.5 w-3.5 shrink-0 text-faint" />
                ) : (
                  <Folder className="h-3.5 w-3.5 shrink-0 text-faint" />
                )}
                <span className="min-w-0 flex-1 truncate text-[length:var(--ui-text-body)] text-primary">
                  {entry.name}
                </span>
                {entry.is_alc_project && (
                  <span className="shrink-0 text-[length:var(--ui-text-label)] text-live">
                    alc project
                  </span>
                )}
              </button>
              {/* Selecting is separate from descending. Clicking a row opens it;
                  the check picks it. Conflating the two makes a folder you meant
                  to look inside register itself instead. */}
              <button
                type="button"
                aria-label={`Use ${entry.name}`}
                title={`Use ${entry.name}`}
                onClick={() => onPick(entry.path)}
                className="mr-1 flex h-[var(--ui-control-h)] w-[var(--ui-control-h)] shrink-0 items-center justify-center rounded-xs text-faint hover:bg-hover hover:text-live"
              >
                <Check className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      </div>

      {data && (
        <div className="flex items-center justify-between gap-2 border-t border-border bg-raised px-2 py-1.5">
          <span className="truncate text-[length:var(--ui-text-label)] text-faint">
            {data.is_alc_project
              ? 'This directory is an ALC project.'
              : data.is_git_repo
                ? 'A git repository, not yet an ALC project.'
                : 'Pick this directory, or open one below.'}
          </span>
          <button
            type="button"
            onClick={() => onPick(data.path)}
            className="shrink-0 rounded-xs border border-border px-2 py-1 text-[length:var(--ui-text-label)] text-primary hover:bg-hover"
          >
            Use this directory
          </button>
        </div>
      )}
    </div>
  )
}
