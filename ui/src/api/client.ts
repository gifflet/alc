// client.ts — Thin typed fetch wrapper over the `alc ui` REST API.
//
// One function per endpoint the Phase 2 (read-only) shell needs. Everything is
// GET except project register/deregister and exec dispatch/cancel, which the
// project selector and live-test flow use. Errors surface as ApiError with the
// backend's detail so the UI can show a clear message.
import type {
  AdoptResult,
  AuditWindow,
  BranchList,
  CheckHistoryEntry,
  ChecksAudit,
  CollectionItem,
  CollectionName,
  CommandSchema,
  DiscardBranchesBody,
  DiscardResult,
  EngineInfo,
  ExecView,
  FleetResponse,
  InboxResponse,
  ReviewComment,
  ReviewResult,
  HireResult,
  LandResult,
  LintResult,
  LoopLedger,
  LoopState,
  MetricSeries,
  OnboardApplyResult,
  OnboardProposal,
  ProjectSummary,
  PromptDetail,
  PromptEntry,
  Queue,
  QueueTask,
  RawParsed,
  RemoveResult,
  RetireResult,
  RunArtifacts,
  RunConfig,
  RunDetail,
  RunsPage,
  ScheduleStatus,
  ScorecardTotals,
  Signal,
  SignalIngestPayload,
  TeamRoster,
  VariantDiff,
  VariantRow,
  Violation,
  WorktreeStatus,
  DirectoryListing,
  CloneStarted,
} from './types'

import { clearToken, getToken } from '../app/token'

export class ApiError extends Error {
  status: number
  detail: unknown
  /** Structured Policy Gate / validator violations, when the backend sent them. */
  violations: Violation[]
  constructor(message: string, status: number, detail: unknown, violations: Violation[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.violations = violations
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    // A rejected token is worse than no token: it would keep failing silently on
    // every query. Drop it so the UI can ask for a fresh one.
    if (res.status === 401) clearToken()
    let detail: unknown = null
    let violations: Violation[] = []
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      detail = body?.detail ?? body
      if (typeof detail === 'string') message = detail
      if (Array.isArray(body?.violations)) violations = body.violations as Violation[]
    } catch {
      // Non-JSON error body — keep the status line as the message.
    }
    throw new ApiError(message, res.status, detail, violations)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const proj = (id: string) => `/api/projects/${encodeURIComponent(id)}`

/** URL for an artifact's raw bytes, for an `<a href>` — not a fetch. The
 * browser opens it directly, rendered with the content-type the backend
 * infers from the extension. `path` is echoed back exactly as the artifacts
 * list returned it — never rewritten. */
export function artifactFileUrl(id: string, path: string): string {
  return `${proj(id)}/artifacts/file?path=${encodeURIComponent(path)}`
}

export const api = {
  // Registry
  listProjects: () => request<ProjectSummary[]>('/api/projects'),
  addProject: (path: string, name?: string) =>
    request<ProjectSummary>('/api/projects', {
      method: 'POST',
      body: JSON.stringify({ path, name }),
    }),
  removeProject: (id: string) =>
    request<void>(`/api/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  /** List the directories inside `path` (defaults to the server's $HOME). */
  browseDirectory: (path?: string, showHidden = false) => {
    const query = new URLSearchParams()
    if (path) query.set('path', path)
    if (showHidden) query.set('show_hidden', 'true')
    const suffix = query.toString()
    return request<DirectoryListing>(`/api/fs/browse${suffix ? `?${suffix}` : ''}`)
  },

  /** Start `git clone` on the host; returns the exec to follow. */
  cloneRepository: (url: string, parent: string, name?: string) =>
    request<CloneStarted>('/api/fs/clone', {
      method: 'POST',
      body: JSON.stringify({ url, parent, name }),
    }),

  /** Create a directory and scaffold an Operator Layer in it. */
  newProject: (parent: string, name: string, git = true) =>
    request<CloneStarted>('/api/fs/new-project', {
      method: 'POST',
      body: JSON.stringify({ parent, name, git }),
    }),

  /** Scaffold an Operator Layer inside a directory that already holds code. */
  adoptDirectory: (path: string) =>
    request<CloneStarted>('/api/fs/adopt', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  // Config viewers
  getManifest: (id: string) => request<RawParsed>(`${proj(id)}/manifest`),
  listCollection: (id: string, collection: CollectionName) =>
    request<CollectionItem[]>(`${proj(id)}/${collection}`),
  getCollectionItem: (id: string, collection: CollectionName, name: string) =>
    request<RawParsed>(`${proj(id)}/${collection}/${encodeURIComponent(name)}`),
  listPrompts: (id: string) => request<PromptEntry[]>(`${proj(id)}/prompts`),
  getPrompt: (id: string, name: string) =>
    request<PromptDetail>(`${proj(id)}/prompts/${encodeURIComponent(name)}`),

  // Config writers
  putManifest: (id: string, raw: string) =>
    request<RawParsed>(`${proj(id)}/manifest`, { method: 'PUT', body: JSON.stringify({ raw }) }),
  putCollectionItem: (id: string, collection: CollectionName, name: string, raw: string) =>
    request<RawParsed>(`${proj(id)}/${collection}/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify({ raw }),
    }),
  createCollectionItem: (id: string, collection: CollectionName, name: string, raw = '') =>
    request<RawParsed>(`${proj(id)}/${collection}`, {
      method: 'POST',
      body: JSON.stringify({ name, raw }),
    }),
  deleteCollectionItem: (id: string, collection: CollectionName, name: string) =>
    request<void>(`${proj(id)}/${collection}/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  putPrompt: (id: string, name: string, raw: string) =>
    request<PromptDetail>(`${proj(id)}/prompts/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify({ raw }),
    }),
  createPrompt: (id: string, name: string, raw = '') =>
    request<PromptDetail>(`${proj(id)}/prompts`, {
      method: 'POST',
      body: JSON.stringify({ name, raw }),
    }),
  deletePrompt: (id: string, name: string) =>
    request<void>(`${proj(id)}/prompts/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  // Queue / runs / loops
  getQueue: (id: string) => request<Queue>(`${proj(id)}/queue`),
  enqueueTask: (id: string, task: Partial<QueueTask>) =>
    request<{ stem: string }>(`${proj(id)}/queue`, {
      method: 'POST',
      body: JSON.stringify(task),
    }),
  /** Batch enqueue: each entry has the same shape as a single
   * task, sharing no write path with `enqueueTask` beyond the backend's own
   * per-item `enqueue`. */
  enqueueBatch: (id: string, tasks: Partial<QueueTask>[]) =>
    request<{ stems: string[] }>(`${proj(id)}/queue/batch`, {
      method: 'POST',
      body: JSON.stringify({ tasks }),
    }),
  deletePending: (id: string, stem: string) =>
    request<void>(`${proj(id)}/queue/${encodeURIComponent(stem)}`, { method: 'DELETE' }),
  dismissQueueFailure: (id: string, stem: string) =>
    request<{ dismissed: string }>(`${proj(id)}/queue/dismiss`, {
      method: 'POST',
      body: JSON.stringify({ stem }),
    }),
  archiveSignal: (id: string, name: string) =>
    request<{ archived: string }>(`${proj(id)}/queue/signals/archive`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  retryQueue: (id: string, body: { stem?: string; all?: boolean }) =>
    request<{ enqueued: string[] }>(`${proj(id)}/queue/retry`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listRuns: (id: string, limit = 50, offset = 0) =>
    request<RunsPage>(`${proj(id)}/runs?limit=${limit}&offset=${offset}`),
  getFleet: (id: string) => request<FleetResponse>(`${proj(id)}/fleet`),
  getInbox: (id: string) => request<InboxResponse>(`${proj(id)}/inbox`),
  getBranchDiff: (id: string, branch: string) =>
    request<VariantDiff>(`${proj(id)}/branches/diff?branch=${encodeURIComponent(branch)}`),
  submitReview: (
    id: string,
    body: { branch: string; comments: ReviewComment[]; kind?: string; name?: string | null },
  ) =>
    request<ReviewResult>(`${proj(id)}/branches/review`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getRun: (id: string, stem: string, offset = 0) =>
    request<RunDetail>(`${proj(id)}/runs/${encodeURIComponent(stem)}?offset=${offset}`),
  getLoopState: (id: string, name: string) =>
    request<LoopState>(`${proj(id)}/loops/${encodeURIComponent(name)}/state`),
  getLoopLedger: (id: string, name: string) =>
    request<LoopLedger>(`${proj(id)}/loops/${encodeURIComponent(name)}/ledger`),
  /** The repo / working-tree status (RepoStatus): `dirty` outside `.alc/`, plus
   * branch / upstream / ahead / behind / untracked. A dirty tree only WARNS (the
   * run commits just what it produces). Off-git degrades to `available: false`.
   * Pushed LIVE: watch.py emits a debounced `worktree_changed` that invalidates
   * this query, so a split-screen edit/commit/stash reflects without a reload.
   * `ahead`/`behind` are as of the last fetch — the backend never fetches. */
  getWorktree: (id: string) => request<WorktreeStatus>(`${proj(id)}/worktree`),

  // Branches (`alc land` / `alc discard`)
  getBranches: (id: string) => request<BranchList>(`${proj(id)}/branches`),
  /** `mode` overrides the project manifest's own `delivery.mode` for this land
   * (DeliverySpec, `local`/`push`/`pr`); omitted keeps the wire body exactly
   * what it was before delivery existed. */
  landBranches: (id: string, branches?: string[], mode?: 'local' | 'push' | 'pr') =>
    request<LandResult>(`${proj(id)}/branches/land`, {
      method: 'POST',
      body: JSON.stringify({
        ...(branches !== undefined ? { branches } : {}),
        ...(mode !== undefined ? { mode } : {}),
      }),
    }),
  discardBranches: (id: string, body: DiscardBranchesBody) =>
    request<DiscardResult>(`${proj(id)}/branches/discard`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // Variants (`alc compare` / `alc adopt` / `alc compare --diff`)
  getVariants: (id: string) => request<VariantRow[]>(`${proj(id)}/variants`),
  adoptVariant: (id: string, branch: string) =>
    request<AdoptResult>(`${proj(id)}/variants/adopt`, {
      method: 'POST',
      body: JSON.stringify({ branch }),
    }),
  // `branch` is a query param (it carries a `/`, like /artifacts/file?path=).
  getVariantDiff: (id: string, branch: string) =>
    request<VariantDiff>(`${proj(id)}/variants/diff?branch=${encodeURIComponent(branch)}`),

  // Signals (`alc signal ingest` / `signal list`)
  getSignals: (id: string) => request<Signal[]>(`${proj(id)}/signals`),
  ingestSignal: (id: string, payload: SignalIngestPayload) =>
    request<{ path: string }>(`${proj(id)}/signals`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Team (Archetype Packs + Mix Health)
  getTeam: (id: string) => request<TeamRoster>(`${proj(id)}/team`),
  hireArchetype: (id: string, archetype: string, force = false) =>
    request<HireResult>(`${proj(id)}/team/hire`, {
      method: 'POST',
      body: JSON.stringify({ archetype, force }),
    }),
  retireMember: (id: string, archetype: string) =>
    request<RetireResult>(`${proj(id)}/team/retire`, {
      method: 'POST',
      body: JSON.stringify({ archetype }),
    }),
  removeMember: (id: string, archetype: string) =>
    request<RemoveResult>(`${proj(id)}/team/remove`, {
      method: 'POST',
      body: JSON.stringify({ archetype }),
    }),

  // Health / metrics
  getLint: (id: string) => request<LintResult>(`${proj(id)}/lint`),
  getEngines: (id: string) => request<EngineInfo[]>(`${proj(id)}/engines`),
  getScorecard: (id: string) => request<ScorecardTotals>(`${proj(id)}/scorecard`),

  // Measurement: metric series, run artifacts (e2e evidence), audit window
  getMetrics: (id: string, check?: string) =>
    request<MetricSeries>(`${proj(id)}/metrics${check ? `?check=${encodeURIComponent(check)}` : ''}`),
  getRunArtifacts: (id: string, stem: string) =>
    request<RunArtifacts>(`${proj(id)}/runs/${encodeURIComponent(stem)}/artifacts`),
  getAudit: (id: string, since: string) =>
    request<AuditWindow>(`${proj(id)}/audit?since=${encodeURIComponent(since)}`),

  // Checks (`alc checks history` / `alc checks audit`)
  getChecksHistory: (id: string) =>
    request<CheckHistoryEntry[]>(`${proj(id)}/checks/history`),
  getChecksAudit: (id: string) => request<ChecksAudit>(`${proj(id)}/checks/audit`),

  // Onboard (`alc onboard`, harvest-only): propose, then apply. `stage` is the
  // operator's optional product-stage answer; the server rebuilds the whole
  // proposal itself, so apply never sends check data back.
  getOnboardProposal: (id: string, stage?: string) =>
    request<OnboardProposal>(
      `${proj(id)}/checks/onboard${stage ? `?stage=${encodeURIComponent(stage)}` : ''}`,
    ),
  applyOnboard: (id: string, stage?: string) =>
    request<OnboardApplyResult>(`${proj(id)}/checks/onboard/apply`, {
      method: 'POST',
      body: JSON.stringify({ stage: stage ?? null }),
    }),

  // Run configurations
  getCommands: () => request<CommandSchema>('/api/commands'),
  listRunConfigs: (id: string) =>
    request<{ configs: RunConfig[] }>(`${proj(id)}/run-configs`),
  createRunConfig: (id: string, cfg: RunConfig) =>
    request<RunConfig>(`${proj(id)}/run-configs`, {
      method: 'POST',
      body: JSON.stringify(cfg),
    }),
  updateRunConfig: (id: string, name: string, cfg: RunConfig) =>
    request<RunConfig>(`${proj(id)}/run-configs/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(cfg),
    }),
  deleteRunConfig: (id: string, name: string) =>
    request<void>(`${proj(id)}/run-configs/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  // Execs
  listExecs: () => request<ExecView[]>('/api/execs'),
  getExec: (execId: string) => request<ExecView>(`/api/execs/${encodeURIComponent(execId)}`),
  startExec: (id: string, command: string, args: Record<string, unknown> = {}) =>
    request<{ exec_id: string }>(`${proj(id)}/exec`, {
      method: 'POST',
      body: JSON.stringify({ command, args }),
    }),
  cancelExec: (execId: string) =>
    request<{ cancelled: boolean }>(
      `/api/execs/${encodeURIComponent(execId)}/cancel`,
      { method: 'POST' },
    ),

  // Schedule (`alc schedule list`) — read-only, project-independent; install/
  // remove stays a CLI-only operation.
  getSchedule: () => request<ScheduleStatus>('/api/schedule'),
}
