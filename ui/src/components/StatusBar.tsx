// StatusBar.tsx — 24px footer: project, engine health, WS link, active execs.
import { Cpu, Keyboard, Loader2 } from 'lucide-react'
import { useEngines, useExecs } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useWs } from '../ws/WsProvider'
import { RepoStatus } from './RepoStatus'
import { StatusDot } from './StatusDot'

export function StatusBar({
  projectName,
  onOpenShortcuts,
}: {
  projectName: string
  onOpenShortcuts: () => void
}) {
  const id = useProjectId()
  const { status } = useWs()
  const { data: engines } = useEngines(id)
  const { data: execs } = useExecs()
  const running = (execs ?? []).filter((e) => e.project_id === id && e.status === 'running').length

  return (
    <footer className="flex h-6 shrink-0 items-center gap-4 border-t border-border bg-panel px-3 text-[11px] text-muted">
      <span className="flex items-center gap-1.5 text-primary">
        <Cpu className="h-3 w-3 text-muted" />
        {projectName}
      </span>

      <RepoStatus />

      <span className="flex items-center gap-1.5">
        {(engines ?? []).map((e) => (
          <StatusDot
            key={e.name}
            tone={e.healthy ? 'live' : 'error'}
            title={`${e.name} (${e.type ?? 'engine'}) — ${e.healthy ? 'healthy' : 'unhealthy'}`}
          />
        ))}
        <span className="text-faint">engines</span>
      </span>

      <span className="ml-auto flex items-center gap-1.5">
        {running > 0 && (
          <span className="flex items-center gap-1 text-running">
            <Loader2 className="h-3 w-3 animate-spin" />
            {running} exec{running === 1 ? '' : 's'}
          </span>
        )}
      </span>

      <span className="flex items-center gap-1.5">
        <StatusDot
          tone={status === 'open' ? 'live' : 'idle'}
          pulse={status === 'open'}
          title={`WebSocket ${status}`}
        />
        <span className={status === 'open' ? 'text-live' : 'text-faint'}>
          {status === 'open' ? 'live' : 'reconnecting'}
        </span>
      </span>

      <button
        type="button"
        aria-label="Keyboard shortcuts"
        title="Keyboard shortcuts (?)"
        onClick={onOpenShortcuts}
        className="flex items-center text-faint transition-colors duration-120 hover:text-primary"
      >
        <Keyboard className="h-3.5 w-3.5" />
      </button>
    </footer>
  )
}
