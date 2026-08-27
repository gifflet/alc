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

function statusTone(exec: ExecEntry): Tone {
  if (exec.status === 'running') return 'running'
  return exec.exitCode === 0 ? 'live' : 'error'
}

/** A short, human label for an exec ("run", "flow"…) used in the rail. */
function label(exec: ExecEntry): string {
  return exec.command || 'exec'
}

function ExecRow({ exec, active, onSelect }: { exec: ExecEntry; active: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex h-[26px] w-full items-center gap-2 px-2 text-left text-[length:var(--ui-text-body)] transition-colors duration-120 ${
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
    <div className="flex h-7 shrink-0 items-center gap-2 border-b border-border bg-panel px-2 text-[length:var(--ui-text-label)]">
      <StatusDot tone={statusTone(exec)} pulse={running} />
      <span className="font-mono text-muted">{label(exec)}</span>
      {running ? (
        <span className="text-running">running</span>
      ) : (
        <span className={exec.exitCode === 0 ? 'text-live' : 'text-error'}>exit {exec.exitCode}</span>
      )}

      {exec.runStems.map((stem) => (
        <button
          key={stem}
          type="button"
          onClick={() => uiStore.openTab({ target: { type: 'run', stem }, title: stem })}
          className="flex min-h-[var(--ui-control-h)] items-center gap-1 rounded-panel border border-border px-1.5 text-[length:var(--ui-text-label)] text-muted hover:bg-hover hover:text-primary"
        >
          <Radio className="h-3 w-3" />
          view run
        </button>
      ))}

      <div className="ml-auto flex items-center gap-1">
        {running && (
          <button
            type="button"
            onClick={() => void api.cancelExec(exec.id).catch(() => {})}
            className="flex min-h-[var(--ui-control-h)] items-center gap-1 rounded-panel border border-error/50 px-1.5 text-error hover:bg-error/10"
          >
            <Square className="h-3 w-3" />
            Cancel
          </button>
        )}
        <button
          type="button"
          aria-label="Clear output"
          onClick={() => execStore.clear(exec.id)}
          className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint hover:text-primary"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Close exec"
          onClick={() => execStore.remove(exec.id)}
          className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint hover:text-primary"
        >
          <X className="h-3.5 w-3.5" />
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

  return (
    <div className="flex h-full min-h-0">
      <div className="w-44 shrink-0 overflow-auto border-r border-border bg-panel">
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
