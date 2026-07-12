// types.ts — TypeScript shapes mirroring the `alc ui` backend responses.
//
// Every type here is derived from the FastAPI routes and pydantic models in the
// alc repo (routes_*.py, service.py, collections.py, models.py). Keep them in
// sync with the backend; the UI never invents fields.

// ---------------------------------------------------------------------------
// Projects (registry)
// ---------------------------------------------------------------------------

export interface ProjectSummary {
  id: string
  name: string
  path: string
  available: boolean
  default_engine: string | null
  queue_pending: number
}

// ---------------------------------------------------------------------------
// Config: manifest, collections, prompts
// ---------------------------------------------------------------------------

export interface RawParsed {
  raw: string
  parsed: unknown
}

export interface CollectionItem {
  name: string
  mtime: number
}

export type CollectionName =
  | 'blueprints'
  | 'flows'
  | 'specialists'
  | 'loops'
  | 'primers'

export interface PromptEntry {
  name: string
  kind: string
  source: string
  reserved: boolean
  ejected: boolean
}

export interface PromptDetail {
  raw: string
  reserved: boolean
  ejected: boolean
}

// ---------------------------------------------------------------------------
// Scorecard / reports (models.py)
// ---------------------------------------------------------------------------

export interface Scorecard {
  span: number
  passes: number
  streak: number
  touch: number
}

export interface AttemptRecord {
  index: number
  engine_ok: boolean
  failed_checks: string[]
}

export interface RunReport {
  blueprint: string
  engine: string
  success: boolean
  attempts: AttemptRecord[]
  scorecard: Scorecard
  output_text: string
  changed_files: string[]
  usage: unknown
}

export interface FlowReport {
  flow: string
  engine: string
  success: boolean
  stages: RunReport[]
  scorecard: Scorecard
  commit_sha: string | null
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

export interface QueueTask {
  flow: string
  task: string
  engine: string | null
  isolate: boolean
  kind: 'flow' | 'specialist'
  name: string | null
  retries: number
  retry_of: string | null
  id: string | null
  depends_on: string[]
}

export interface PendingTask {
  stem: string
  mtime: number
  task: QueueTask
}

export interface DoneTask {
  stem: string
  mtime: number
  task: QueueTask | null
  report: FlowReport | null
}

export interface Queue {
  pending: PendingTask[]
  done: DoneTask[]
}

// ---------------------------------------------------------------------------
// Runs (event logs)
// ---------------------------------------------------------------------------

export interface RunSummary {
  stem: string
  kind: string
  mtime: number
  size: number
  finished: boolean
}

export interface RunsPage {
  runs: RunSummary[]
  total: number
}

/** One JSONL line from a run log: always carries ts + event, plus payload. */
export interface RunEvent {
  ts: string
  event: string
  // Payload fields (present depending on `event`). Typed loosely on purpose:
  // the formatter/timeline narrow by `event`.
  [key: string]: unknown
}

export interface RunDetail {
  events: RunEvent[]
  next_offset: number
}

// ---------------------------------------------------------------------------
// Lint / engines / aggregate scorecard
// ---------------------------------------------------------------------------

export interface Violation {
  rule: string
  severity: string
  message: string
}

export interface LintResult {
  violations: Violation[]
}

export interface EngineInfo {
  name: string
  type: string | null
  default: boolean
  tiers: Record<string, string>
  healthy: boolean
}

export interface ScorecardTotals {
  reports: number
  successes: number
  failures: number
  span_total: number
  passes_total: number
  streak_total: number
  touch_total: number
}

// ---------------------------------------------------------------------------
// Loops
// ---------------------------------------------------------------------------

export type LoopStatus = 'pending' | 'running' | 'stopped'

export interface LoopState {
  name: string
  status: LoopStatus
  cycle: number
  consecutive_no_progress: number
  budget_used: Record<string, number>
  stopped_reason: string | null
}

export interface CycleRecord {
  cycle: number
  replenished: number
  drained: number
  succeeded: number
  failed: number
  merged: number
  left: number
  replenish_failed: boolean
  progress: boolean
  budget_delta: Record<string, number>
  stopped_reason: string | null
}

export interface LoopLedger {
  records: CycleRecord[]
}

// ---------------------------------------------------------------------------
// Execs
// ---------------------------------------------------------------------------

export type ExecStatus = 'running' | 'finished' | 'cancelled' | 'error'

export interface ExecView {
  id: string
  project_id: string
  command: string
  status: ExecStatus
  exit_code: number | null
  output: string[]
}

// ---------------------------------------------------------------------------
// WebSocket messages (ws.py + watch.py + execs.py)
// ---------------------------------------------------------------------------

export interface WsSubscribed {
  type: 'subscribed'
  project_id: string
}
export interface WsRunEvent {
  type: 'run_event'
  project_id: string
  stem: string
  event: RunEvent
}
export interface WsQueueChanged {
  type: 'queue_changed'
  project_id: string
}
export interface WsReportAdded {
  type: 'report_added'
  project_id: string
  stem: string
}
export interface WsLoopChanged {
  type: 'loop_changed'
  project_id: string
  name: string
}
export interface WsConfigChanged {
  type: 'config_changed'
  project_id: string
  resource: string
}
export interface WsExecOutput {
  type: 'exec_output'
  project_id: string
  exec_id: string
  stream: 'stdout' | 'stderr'
  line: string
}
export interface WsExecFinished {
  type: 'exec_finished'
  project_id: string
  exec_id: string
  exit_code: number
}
export interface WsProjectListChanged {
  type: 'project_list_changed'
  project_id: null
}

export type WsMessage =
  | WsSubscribed
  | WsRunEvent
  | WsQueueChanged
  | WsReportAdded
  | WsLoopChanged
  | WsConfigChanged
  | WsExecOutput
  | WsExecFinished
  | WsProjectListChanged
