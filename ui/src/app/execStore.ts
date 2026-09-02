// execStore.ts — Live state for `alc` execs launched from the UI.
//
// A tiny external store (useSyncExternalStore, mirroring uiStore) fed by the WS
// bridge: each exec keeps its streamed output tail, status/exit code, and any
// runs that appeared in .alc/runs/ while it was running. State is session-only
// and seeded from GET /api/execs on load + reconnect so in-flight execs recover.
import { useSyncExternalStore } from 'react'
import type { ExecStatus, ExecView } from '../api/types'

const MAX_LINES = 2000
// A run log is written by the subprocess and only surfaces on the bus a beat
// after exec_finished for fast (mock) runs, so a just-finished exec still claims
// the run stem for this long after it exits.
const RUN_ATTACH_GRACE_MS = 5000

export interface ExecEntry {
  id: string
  projectId: string
  command: string
  status: ExecStatus
  exitCode: number | null
  lines: string[]
  /** epoch ms the exec exited (drives the run-attach grace window). */
  finishedAt: number | null
  /** Run stems (.alc/runs/*) observed while (or just after) this exec ran. */
  runStems: string[]
}

export interface ExecStoreState {
  execs: ExecEntry[]
  selectedId: string | null
}

function capPush(lines: string[], line: string): string[] {
  const next = [...lines, line]
  return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next
}

function createStore() {
  const listeners = new Set<() => void>()
  let state: ExecStoreState = { execs: [], selectedId: null }

  function set(next: ExecStoreState): void {
    state = next
    listeners.forEach((l) => l())
  }

  /** Return a state with one exec replaced by fn(exec) (no-op if absent). */
  function withExec(id: string, fn: (e: ExecEntry) => ExecEntry): ExecStoreState {
    return { ...state, execs: state.execs.map((e) => (e.id === id ? fn(e) : e)) }
  }

  return {
    getState: (): ExecStoreState => state,
    subscribe(listener: () => void): () => void {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },

    /** Register an exec we just launched (or adopt an early-arriving one) and focus it. */
    launch(entry: { id: string; projectId: string; command: string }): void {
      const exists = state.execs.some((e) => e.id === entry.id)
      if (exists) {
        set({ ...withExec(entry.id, (e) => ({ ...e, command: entry.command })), selectedId: entry.id })
        return
      }
      const rec: ExecEntry = {
        ...entry,
        status: 'running',
        exitCode: null,
        lines: [],
        finishedAt: null,
        runStems: [],
      }
      set({ execs: [...state.execs, rec], selectedId: entry.id })
    },

    /** Append one streamed output line (creating a placeholder if unseen). */
    output(msg: { execId: string; projectId: string; line: string }): void {
      if (!state.execs.some((e) => e.id === msg.execId)) {
        const rec: ExecEntry = {
          id: msg.execId,
          projectId: msg.projectId,
          command: '',
          status: 'running',
          exitCode: null,
          lines: [msg.line],
          finishedAt: null,
          runStems: [],
        }
        set({ ...state, execs: [...state.execs, rec], selectedId: state.selectedId ?? msg.execId })
        return
      }
      set(withExec(msg.execId, (e) => ({ ...e, lines: capPush(e.lines, msg.line) })))
    },

    /** Record the exit code and derive a terminal status. */
    finished(msg: { execId: string; exitCode: number }): void {
      set(
        withExec(msg.execId, (e) => ({
          ...e,
          status: e.status === 'running' ? (msg.exitCode === 0 ? 'finished' : 'error') : e.status,
          exitCode: msg.exitCode,
          finishedAt: Date.now(),
        })),
      )
    },

    /** Attach a run stem to the exec that owns it: the newest running exec of the
     * project, or one that finished within the grace window (fast runs land the
     * run log just after exec_finished). */
    noteRun(projectId: string, stem: string): void {
      const now = Date.now()
      const owner = [...state.execs].reverse().find(
        (e) =>
          e.projectId === projectId &&
          (e.status === 'running' ||
            (e.finishedAt !== null && now - e.finishedAt < RUN_ATTACH_GRACE_MS)),
      )
      if (!owner || owner.runStems.includes(stem)) return
      set(withExec(owner.id, (e) => ({ ...e, runStems: [...e.runStems, stem] })))
    },

    /** Merge server snapshots: update known execs, append unknown ones. */
    seed(views: ExecView[]): void {
      const known = new Set(state.execs.map((e) => e.id))
      const updated = state.execs.map((e) => {
        const v = views.find((x) => x.id === e.id)
        if (!v) return e
        return {
          ...e,
          command: e.command || v.command,
          status: v.status,
          exitCode: v.exit_code,
          lines: e.lines.length > 0 ? e.lines : v.output,
        }
      })
      const added = views
          // Execs with no project — a clone, for instance — are followed by
          // the component that started them, over the socket. They have no
          // place in a store whose every query is scoped to a project id.
          .filter((v): v is ExecView & { project_id: string } => v.project_id !== null)
        .filter((v) => !known.has(v.id))
        .map<ExecEntry>((v) => ({
          id: v.id,
          projectId: v.project_id,
          command: v.command,
          status: v.status,
          exitCode: v.exit_code,
          lines: v.output,
          finishedAt: v.status === 'running' ? null : Date.now(),
          runStems: [],
        }))
      const execs = [...updated, ...added]
      set({ execs, selectedId: state.selectedId ?? execs.at(-1)?.id ?? null })
    },

    select(id: string): void {
      set({ ...state, selectedId: id })
    },

    clear(id: string): void {
      set(withExec(id, (e) => ({ ...e, lines: [] })))
    },

    remove(id: string): void {
      const idx = state.execs.findIndex((e) => e.id === id)
      if (idx === -1) return
      const execs = state.execs.filter((e) => e.id !== id)
      let selectedId = state.selectedId
      if (selectedId === id) selectedId = (execs[idx] ?? execs[idx - 1] ?? null)?.id ?? null
      set({ ...state, execs, selectedId })
    },

    reset(): void {
      set({ execs: [], selectedId: null })
    },
  }
}

/** The running exec that owns *stem*'s run, when the store can prove it.

 * Match by observed run stems first; fall back to "the only running exec of
 * this project" — unambiguous by counting, which is what an operator's eye
 * does. Null when nothing running matches: a cancel control must never guess
 * between two candidates (finding 37 wants cancel WHERE the run is watched,
 * not a roulette). */
export function runningExecForStem(
  state: ExecStoreState,
  projectId: string,
  stem: string,
): ExecEntry | null {
  const running = state.execs.filter(
    (e) => e.status === 'running' && e.projectId === projectId,
  )
  const byStem = running.find((e) => e.runStems.includes(stem))
  if (byStem) return byStem
  return running.length === 1 ? running[0] : null
}

export const execStore = createStore()

/** Subscribe a component to the whole exec store. */
export function useExecState(): ExecStoreState {
  return useSyncExternalStore(execStore.subscribe, execStore.getState)
}
