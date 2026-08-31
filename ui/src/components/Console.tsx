// Console.tsx — Multi-exec live console: pick a run, tail its output, cancel it.
//
// Left rail lists this project's execs (status dot + command); the pane streams
// the selected exec's output with pausable auto-scroll (ConsolePane). Header
// shows the exit code, a Cancel for running execs, clear/close, and "view run"
// links for any runs that appeared while the exec ran.
import { Radio, Square, Trash2, X } from 'lucide-react'
import { api } from '../api/client'
import { useProjectId } from '../app/ProjectContext'
import { execStore, useExecState } from '../app/execStore'
import { uiStore } from '../app/uiStore'
import type { ExecEntry } from '../app/execStore'
import { ConsolePane } from './ConsolePane'
import { EmptyState } from './EmptyState'
import { StatusDot } from './StatusDot'
import type { Tone } from './StatusDot'
import { ActionButton } from './ActionButton'

function statusTone(exec: ExecEntry): Tone {
  if (exec.status === 'running') return 'running'
  return exec.exitCode === 0 ? 'live' : 'error'
}

/** A short, human label for an exec ("run", "flow"…) used in the rail. */
function label(exec: ExecEntry): string {
  return exec.command || 'exec'
}

function ExecRow({ exec, active, onSelect }: { exec: ExecEntry; active: boolean; onSelect: () => void }) {
  // h from the density token, not a hardcoded 26px: every other row in the app
  // scales with density (32/40/48px), and 26px was also a sub-44px tap target
  // on a phone — one the route sweeps never saw, because the panel opens
  // closed. Width: a chip on narrow screens (sized to content, capped), a full
  // rail row from sm up.
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex h-[var(--ui-row-h)] max-w-[60vw] shrink-0 items-center gap-2 px-3 text-left text-[length:var(--ui-text-body)] transition-colors duration-120 sm:w-full sm:max-w-none ${
        active ? 'bg-hover text-primary' : 'text-muted hover:bg-hover'
      }`}
    >
      <StatusDot tone={statusTone(exec)} pulse={exec.status === 'running'} />
      <span className="min-w-0 flex-1 truncate font-mono">{label(exec)}</span>
      <span className="tabular shrink-0 text-[length:var(--ui-text-label)] text-faint">{exec.id.slice(0, 6)}</span>
    </button>
  )
}

function ExecHeader({ exec }: { exec: ExecEntry }) {
  const running = exec.status === 'running'
  return (
    // min-h from the control token: at h-7 (28px) the header could not even
    // contain its own buttons' 44px coarse-pointer hit areas, and the title sat
    // at label size. The title reads at body size now — it names what the whole
    // pane shows.
    <div className="flex min-h-[var(--ui-control-h)] shrink-0 items-center gap-2 border-b border-border bg-panel px-2 text-[length:var(--ui-text-label)]">
      <StatusDot tone={statusTone(exec)} pulse={running} />
      <span className="font-mono text-[length:var(--ui-text-body)] text-muted">{label(exec)}</span>
      {running ? (
        <span className="text-running">running</span>
      ) : (
        <span className={exec.exitCode === 0 ? 'text-live' : 'text-error'}>exit {exec.exitCode}</span>
      )}

      {exec.runStems.map((stem) => (
        <ActionButton
          key={stem}
          onClick={() => uiStore.openTab({ target: { type: 'run', stem }, title: stem })}
          tone="ghost"
          size="sm"
        >
          <Radio className="h-3 w-3" />
          view run
        </ActionButton>
      ))}

      <div className="ml-auto flex items-center gap-1">
        {running && (
          <ActionButton
            onClick={() => void api.cancelExec(exec.id).catch(() => {})}
            tone="error"
            size="md"
          >
            <Square className="h-3 w-3" />
            Cancel
          </ActionButton>
        )}
        <button
          type="button"
          aria-label="Clear output"
          onClick={() => execStore.clear(exec.id)}
          className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint hover:text-primary"
        >
          <Trash2 className="h-4 w-4" />
        </button>
        <button
          type="button"
          aria-label="Close exec"
          onClick={() => execStore.remove(exec.id)}
          className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint hover:text-primary"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

export function Console() {
  const id = useProjectId()
  const { execs, selectedId } = useExecState()
  const mine = execs.filter((e) => e.projectId === id)
  const selected = mine.find((e) => e.id === selectedId) ?? mine.at(-1)

  if (mine.length === 0 || !selected) {
    return <EmptyState icon={Radio} message="No executions yet — run a blueprint, flow, or drain the queue." />
  }

  // Stacked on narrow screens, side-by-side from sm up. The fixed w-44 rail was
  // 43% of a 411px panel — desktop IDE proportions on a phone, with the output
  // wrapping at every other word in what was left. As a horizontal chip strip
  // the list costs one row and the output gets the full width.
  return (
    <div className="flex h-full min-h-0 flex-col sm:flex-row">
      <div className="flex shrink-0 overflow-x-auto border-b border-border bg-panel sm:block sm:w-44 sm:overflow-y-auto sm:overflow-x-visible sm:border-b-0 sm:border-r">
        {mine.map((exec) => (
          <ExecRow
            key={exec.id}
            exec={exec}
            active={exec.id === selected.id}
            onSelect={() => execStore.select(exec.id)}
          />
        ))}
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <ExecHeader exec={selected} />
        <div className="min-h-0 flex-1">
          <ConsolePane lines={selected.lines} />
        </div>
      </div>
    </div>
  )
}
