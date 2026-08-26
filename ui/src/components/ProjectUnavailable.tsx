// ProjectUnavailable.tsx — The project this URL names cannot be reached.
//
// Without this the shell rendered anyway: the activity bar kept 15 enabled
// buttons, the tool window showed CACHED contents of a project that no longer
// existed, and Fleet said "Nothing running. Dispatch work with `alc run chore`"
// about a project the backend answers 404 for. A control plane must never
// describe a state it cannot observe — so the shell is not rendered at all, and
// the screen states the cause.
import { FolderX, PlugZap } from 'lucide-react'

export type UnavailableReason = 'unregistered' | 'missing'

export function ProjectUnavailable({
  id,
  name,
  path,
  reason,
  onOpenProjects,
}: {
  id: string
  name?: string
  path?: string
  reason: UnavailableReason
  onOpenProjects: () => void
}) {
  const unregistered = reason === 'unregistered'
  const Icon = unregistered ? PlugZap : FolderX

  return (
    <div className="flex h-full items-center justify-center bg-base p-[var(--ui-gap)]">
      <div className="flex w-full max-w-md flex-col items-start gap-[var(--ui-gap)]">
        <div className="flex items-center gap-2 text-primary">
          <Icon className="h-5 w-5 text-faint" strokeWidth={1.75} />
          <h1 className="text-[length:var(--ui-text-title)]">
            {unregistered ? 'Project not registered' : 'Project unavailable'}
          </h1>
        </div>

        <p className="text-[length:var(--ui-text-body)] text-muted">
          {unregistered ? (
            <>
              <code className="font-mono text-faint">{id}</code> is not in this control room. It
              may have been removed here — the files on disk are untouched.
            </>
          ) : (
            <>
              <code className="font-mono text-faint">{name ?? id}</code> no longer has a{' '}
              <code className="font-mono text-faint">.alc/manifest.yaml</code>
              {path ? (
                <>
                  {' '}
                  at <code className="font-mono text-faint">{path}</code>
                </>
              ) : null}
              .
            </>
          )}
        </p>

        <button
          type="button"
          onClick={onOpenProjects}
          className="min-h-[var(--ui-control-h)] rounded-panel border border-border bg-raised px-3 text-[length:var(--ui-text-body)] text-primary hover:bg-hover"
        >
          Open projects
        </button>
      </div>
    </div>
  )
}
