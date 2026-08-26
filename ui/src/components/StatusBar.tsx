// StatusBar.tsx — 24px footer: project, engine health, WS link, active execs.
import { ChevronsUpDown, Keyboard, Loader2, SunMoon } from 'lucide-react'
import { useEngines, useExecs } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useWs } from '../ws/WsProvider'
import { setTheme, useTheme } from '../app/useTheme'
import { Mark } from './Mark'
import { RepoStatus } from './RepoStatus'
import { StatusDot } from './StatusDot'

export function StatusBar({
  projectName,
  onOpenShortcuts,
  onSwitchProject,
}: {
  projectName: string
  onOpenShortcuts: () => void
  onSwitchProject: () => void
}) {
  const id = useProjectId()
  const { status } = useWs()
  const { data: engines } = useEngines(id)
  const { data: execs } = useExecs()
  const running = (execs ?? []).filter((e) => e.project_id === id && e.status === 'running').length
  const theme = useTheme()

  return (
    <footer className="flex h-6 shrink-0 items-center gap-4 border-t border-border bg-panel px-3 text-[length:var(--ui-text-label)] text-muted">
      {/* The project name was already the first thing here; making it the
          switcher means the control sits where the eye goes to answer "which
          project am I in?" rather than in a menu somewhere else. */}
      <button
        type="button"
        onClick={onSwitchProject}
        title="Switch project (Cmd/Ctrl+P)"
        className="flex items-center gap-1.5 rounded-xs text-primary hover:bg-hover"
      >
        <Mark size={12} className="text-muted" />
        {projectName}
        <ChevronsUpDown className="h-3 w-3 text-faint" />
      </button>

      <button
        type="button"
        aria-label={`Theme: ${theme}`}
        title={`Theme: ${theme} — click to switch`}
        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        className="flex items-center text-faint hover:text-primary"
      >
        <SunMoon className="h-3 w-3" />
      </button>

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
