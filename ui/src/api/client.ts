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
  HireResult,
  LandResult,
  LintResult,
  LoopLedger,
  LoopState,
  MetricSeries,
  ProjectSummary,
  PromptDetail,
  PromptEntry,
  Queue,
  QueueTask,
  RawParsed,
  RetireResult,
  RunArtifacts,
  RunConfig,
  RunDetail,
  RunsPage,
  ScorecardTotals,
  Signal,
  SignalIngestPayload,
  TeamRoster,
  VariantRow,
  Violation,
} from './types'

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
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
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
  deletePending: (id: string, stem: string) =>
    request<void>(`${proj(id)}/queue/${encodeURIComponent(stem)}`, { method: 'DELETE' }),
  retryQueue: (id: string, body: { stem?: string; all?: boolean }) =>
    request<{ enqueued: string[] }>(`${proj(id)}/queue/retry`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listRuns: (id: string, limit = 50, offset = 0) =>
    request<RunsPage>(`${proj(id)}/runs?limit=${limit}&offset=${offset}`),
  getRun: (id: string, stem: string, offset = 0) =>
    request<RunDetail>(`${proj(id)}/runs/${encodeURIComponent(stem)}?offset=${offset}`),
  getLoopState: (id: string, name: string) =>
    request<LoopState>(`${proj(id)}/loops/${encodeURIComponent(name)}/state`),
  getLoopLedger: (id: string, name: string) =>
    request<LoopLedger>(`${proj(id)}/loops/${encodeURIComponent(name)}/ledger`),

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

  // Variants (`alc compare` / `alc adopt`)
  getVariants: (id: string) => request<VariantRow[]>(`${proj(id)}/variants`),
  adoptVariant: (id: string, branch: string) =>
    request<AdoptResult>(`${proj(id)}/variants/adopt`, {
      method: 'POST',
      body: JSON.stringify({ branch }),
    }),

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
}
