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
  // Retryable iff this is an OUTSTANDING failure: the latest failed attempt of a
  // lineage no later retry resolved. A failure fixed by a later attempt is false.
  outstanding: boolean
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
  // An UNFINISHED run whose log has gone quiet past the interrupted threshold
  // (manifest.default_timeout_s + margin): no live process behind it.
  stale: boolean
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
  stale: boolean
}

// ---------------------------------------------------------------------------
// Branches (branches.py AlcBranch / merge.py MergeReport) — `alc land`/`alc
// discard` thin wrappers, mirrored 1:1 by routes_branches.py.
// ---------------------------------------------------------------------------

export interface Branch {
  name: string
  label: string
  committed_at: number
  merged: boolean
}

/** GET /branches's shape: outside a git repo, `available` is false and
 * `branches` is empty — never an error. */
export interface BranchList {
  available: boolean
  branches: Branch[]
}

/** Outcome of POST /branches/land (and the `land` half of /variants/adopt):
 * a branch is either integrated (and its ref deleted) or left conflicted for
 * manual resolution — never silently dropped. */
export interface MergeReport {
  merged: string[]
  conflicted: string[]
}

/** POST /branches/land's own response: a MergeReport plus the outcome of the
 * optional push/PR delivery (DeliverySpec, `mode: "push"|"pr"`). `warning` is
 * present only when a delivery step was attempted: `null` once every attempted
 * step succeeded, the failure reason otherwise — never swallowed, and never a
 * sign the local merge above failed too (it already succeeded either way). */
export interface LandResult extends MergeReport {
  warning?: string | null
}

/** Outcome of POST /branches/discard. */
export interface DiscardResult {
  deleted: string[]
  pruned_worktrees: number
  deleted_bundles: string[]
}

/** Body for POST /branches/discard (mirrors routes_branches.DiscardBody). */
export interface DiscardBranchesBody {
  branches: string[]
  worktrees?: boolean
  bundles?: { older_than_days: number }
}

// ---------------------------------------------------------------------------
// Variants (variants.py variant_row) — `alc explore`/`compare`/`adopt`.
// ---------------------------------------------------------------------------

export interface Diffstat {
  adds: number
  dels: number
  files_deleted: number
}

/** engine.Usage, asdict()'d — every field best-effort/optional. */
export interface VariantUsage {
  input_tokens: number | null
  output_tokens: number | null
  cost_usd: number | null
}

/** One GET /variants row (variant_row): flattened straight off a UnitResult,
 * plus the variant's requested engine/tier. `branch` mirrors UnitResult.branch
 * (null only for a unit that never committed — practically always set for an
 * archived variant, which is keyed by its branch name). */
export interface VariantRow {
  branch: string | null
  engine: string | null
  tier: string | null
  success: boolean
  checks: string
  scorecard: Scorecard | null
  usage: VariantUsage | null
  diffstat: Diffstat | null
}

/** Outcome of POST /variants/adopt: the winner's MergeReport plus the
 * unmerged `alc/variant-*` siblings it discarded. */
export interface AdoptResult {
  merged: string[]
  conflicted: string[]
  discarded: string[]
}

// ---------------------------------------------------------------------------
// Signals (models.py Signal) — `alc signal ingest`/`signal list`: typed,
// external events (an error tracker alert, operator feedback, an issue, a
// review comment) a loop's `signals` replenish later drains into demands.
// ---------------------------------------------------------------------------

/** One GET /signals row: service.list_signals prepends `path` to the Signal's
 * own fields (mirrors `alc signal list`). `weight` is reporting-only — no
 * replenish policy reads it today. */
export interface Signal {
  path: string
  kind: 'error' | 'feedback' | 'issue' | 'review'
  source: string
  title: string
  body: string
  ts: number
  weight: number | null
}

/** Body for POST /signals — the ingest form's fields. `ts`/`weight` are left
 * out on purpose: `ts` defaults to now server-side (Signal.ts), and `weight`
 * has zero runtime effect today (reporting-only, no control here). */
export interface SignalIngestPayload {
  kind: Signal['kind']
  source: string
  title: string
  body: string
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
  // Optional: an older backend that predates these two fields omits them —
  // the UI must degrade gracefully rather than break.
  net_lines_total?: number | null
  runs_with_warnings?: number
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
// Team (Archetype Packs + Mix Health) — mirrors service.team_roster /
// service.team_hire, and stagepolicy.MixHealthReport / ArchetypeSpend
// (dataclasses.asdict-serialised as-is; field names match exactly).
// ---------------------------------------------------------------------------

export interface TeamMemberLoop {
  name: string
  status: LoopStatus
  cycle: number
  stopped_reason: string | null
}

/** A hired archetype: its pack files present on disk, and any loops it brought. */
export interface TeamMember {
  archetype: string
  files: string[]
  loops: TeamMemberLoop[]
}

/** One archetype's aggregate spend across archived reports. `archetype` is
 * null for reports whose Blueprint set none — never singled out as off-mix. */
export interface ArchetypeSpend {
  archetype: string | null
  runs: number
  span: number
  cost_usd: number
  net_lines: number
}

/** A stage CORE archetype with zero archived runs, plus the one actionable
 * hint for it: hire it (not on the team), run its loop (hired, brought a loop),
 * or route a demand through its blueprints (hired, no loop). Derived by
 * stagepolicy.mix_health so the CLI and the UI render the same guidance. */
export interface IdleCoreArchetype {
  archetype: string
  hired: boolean
  hint: string
}

/** `stage`/`core`/`secondary` are null/[] when no stage is declared: the
 * breakdown is still built, just never judged against a target mix.
 * `total_runs === 0` means no archived report exists yet — "no data yet".
 * `idle_core` names the core archetypes with no runs and the hint for each. */
export interface MixHealth {
  stage: string | null
  core: string[]
  secondary: string[]
  by_archetype: ArchetypeSpend[]
  total_runs: number
  idle_core: IdleCoreArchetype[]
}

export interface TeamRoster {
  members: TeamMember[]
  mix_health: MixHealth
}

/** POST /team/hire's response: the pack files written, and the post-hire lint. */
export interface HireResult {
  written: string[]
  lint: LintResult
}

/** POST /team/retire's response: the loop file(s) archived into `loops/retired/`. */
export interface RetireResult {
  moved: string[]
}

// ---------------------------------------------------------------------------
// Metrics (metrics.py MetricPoint) — one measurement in a check's time series.
// ---------------------------------------------------------------------------

export interface MetricPoint {
  ts: number
  value: number
  run: string
  // Raw numeric movement vs the point before it — null/"n/a" for a series'
  // first point. Never "good"/"bad": the backend does not persist direction.
  delta: number | null
  trend: 'up' | 'down' | 'flat' | 'n/a'
  // Whether the Verifier ACCEPTED this measurement at record time — the only
  // judgment the UI shows for a point.
  passed: boolean
}

/** GET /metrics's shape: every check's series, keyed by check name. */
export type MetricSeries = Record<string, MetricPoint[]>

// ---------------------------------------------------------------------------
// Checks (checks.py CheckHistory / ChecksAudit) — `alc checks history` /
// `alc checks audit`: two read-only Maintainer reads, dataclasses.asdict-
// serialised as-is; field names match exactly.
// ---------------------------------------------------------------------------

/** One check's aggregate history (check_history), computed from every
 * `check_finished` event across the run logs. */
export interface CheckHistoryEntry {
  name: string
  runs: number
  passes: number
  pass_rate: number
  mean_duration_s: number
  flake_score: number
}

/** [check name, command] — CheckSetAudit.add/unavailable's tuple entries,
 * serialised as a 2-element JSON array. */
export type CheckProposal = [string, string[]]

/** One check_set's proposed state (CheckSetAudit): `add` is available on
 * PATH today but not yet live in the Manifest; `unavailable` still lacks a
 * binary — informational only. */
export interface CheckSetAudit {
  set_name: string
  is_new: boolean
  add: CheckProposal[]
  unavailable: CheckProposal[]
}

/** A Blueprint whose resolved checks are nothing but the smoke placeholder,
 * even though a stack is detected today (SmokeOnlyBlueprint). */
export interface SmokeOnlyBlueprint {
  blueprint: string
  stacks: string[]
}

/** GET /checks/audit's shape (ChecksAudit) — every field is a PROPOSAL;
 * nothing here was written to disk. */
export interface ChecksAudit {
  check_sets: CheckSetAudit[]
  smoke_only_blueprints: SmokeOnlyBlueprint[]
}

// ---------------------------------------------------------------------------
// Onboard (`alc onboard`, harvest-only) — onboard.OnboardProposal / ApplyResult,
// dataclasses.asdict-serialised as-is (the same shape `alc onboard --json`
// emits). GET /checks/onboard proposes; POST /checks/onboard/apply writes.
// ---------------------------------------------------------------------------

/** One check ALC proposes to adopt (onboard.ProposedCheck). Exactly one of
 * `command` (argv token list) or `shell` (a shell one-liner) is set. `available`
 * is a `shutil.which` lookup — a check whose binary is off PATH is written
 * commented-out. `origin` is "harvest" in the UI today; "engine" is kept in the
 * mapping for honesty (the engine `--assist` path stays CLI-only for now). */
export interface ProposedCheck {
  name: string
  command: string[] | null
  shell: string | null
  available: boolean
  origin: string
  source_path: string | null
}

/** GET /checks/onboard's shape (onboard.OnboardProposal) — a PLAN, nothing
 * written. `check_sets` is primarily `{ project: [...] }`; `blueprint_opt_ins`
 * maps a smoke-only blueprint name to the check_set it would opt into; `stage`
 * is only ever the operator's answer (never inferred); `team_hints` are the
 * chosen stage's core archetypes not yet hired; `unknowns` are honest gaps. */
export interface OnboardProposal {
  check_sets: Record<string, ProposedCheck[]>
  blueprint_opt_ins: Record<string, string>
  stage: string | null
  team_hints: string[]
  unknowns: string[]
}

/** POST /checks/onboard/apply's shape (onboard.ApplyResult) on a clean apply:
 * what was written. A BLOCKED apply never reaches here — it is a 422 carrying
 * the violations, like the manifest editor's save. */
export interface OnboardApplyResult {
  applied: boolean
  sets_added: string[]
  blueprints_opted_in: string[]
  stage_set: boolean
  notes: string[]
}

// ---------------------------------------------------------------------------
// Artifacts (artifacts.py RunArtifacts) — e2e evidence a run captured.
// ---------------------------------------------------------------------------

export interface Artifact {
  path: string
  type: string
}

export interface RunArtifacts {
  stem: string
  artifacts: Artifact[]
}

// ---------------------------------------------------------------------------
// Audit (audit.py AuditWindow) — the aggregate over a trailing time window.
// ---------------------------------------------------------------------------

export interface AuditWindow {
  since_epoch: number
  tasks_total: number
  tasks_ok: number
  tasks_failed: number
  span_total: number
  span_avg: number
  passes_total: number
  passes_avg: number
  streak_total: number
  streak_avg: number
  touch_total: number
  touch_avg: number
  changed_files_total: number
  input_tokens_total: number
  output_tokens_total: number
  cost_usd_total: number
}

// ---------------------------------------------------------------------------
// Run configurations (command schema + saved presets)
// ---------------------------------------------------------------------------

/** One command's accepted arguments, from GET /api/commands. */
export interface CommandSpec {
  positionals: string[]
  opt_positionals: string[]
  value_flags: string[]
  bool_flags: string[]
}

/** The whole command whitelist keyed by command name. */
export type CommandSchema = Record<string, CommandSpec>

/** A saved, named {command, args} preset. */
export interface RunConfig {
  name: string
  command: string
  args: Record<string, unknown>
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
// Schedule (schedule.py) — `alc schedule list`, read-only. The crontab is
// host-level, not per-project: `available` is false when the host has no
// `crontab` binary at all (schedule.has_crontab), never an error.
// ---------------------------------------------------------------------------

export interface ScheduleStatus {
  available: boolean
  entries: string[]
}

// ---------------------------------------------------------------------------
// Worktree status (service.worktree_status -> RepoStatus). `dirty` is whether the
// tree has uncommitted work outside `.alc/` — an autonomous run is safe on a dirty
// tree (it commits only what it produces), so the Loops view warns and proceeds, a
// banner that sets expectations, not a block. Off-git (no repo) is `available:
// false` (and `dirty: false`), never an error.
//
// `ahead`/`behind` are measured against the LOCAL remote-tracking ref, as of the
// operator's last fetch — the backend NEVER auto-fetches. They are `null` when
// there is no upstream (unknown), never 0 (which means "in sync"). Every field is
// required: the server always sends them (RepoStatus is a fixed dataclass).
// ---------------------------------------------------------------------------

export interface WorktreeStatus {
  available: boolean
  dirty: boolean
  branch: string | null
  detached: boolean
  upstream: string | null
  ahead: number | null
  behind: number | null
  untracked: number
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
export interface WsRunConfigsChanged {
  type: 'run_configs_changed'
  project_id: string
}
export interface WsSignalsChanged {
  type: 'signals_changed'
  project_id: string
}
/** The live repo/working-tree push (watch.py RepoStatusTracker): a debounced
 * `git status` flipped, so the whole enriched status rides along as `status`. The
 * client invalidates `keys.worktree` on it (see ws/invalidate.ts). */
export interface WsWorktreeChanged {
  type: 'worktree_changed'
  project_id: string
  status: WorktreeStatus
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
  | WsRunConfigsChanged
  | WsSignalsChanged
  | WsWorktreeChanged
