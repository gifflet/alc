// client.ts — Thin typed fetch wrapper over the `alc ui` REST API.
//
// One function per endpoint the Phase 2 (read-only) shell needs. Everything is
// GET except project register/deregister and exec dispatch/cancel, which the
// project selector and live-test flow use. Errors surface as ApiError with the
// backend's detail so the UI can show a clear message.
import type {
  CollectionItem,
  CollectionName,
  EngineInfo,
  ExecView,
  LintResult,
  LoopLedger,
  LoopState,
  ProjectSummary,
  PromptDetail,
  PromptEntry,
  Queue,
  RawParsed,
  RunDetail,
  RunsPage,
  ScorecardTotals,
} from './types'

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail: unknown = null
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      detail = body?.detail ?? body
      if (typeof detail === 'string') message = detail
    } catch {
      // Non-JSON error body — keep the status line as the message.
    }
    throw new ApiError(message, res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const proj = (id: string) => `/api/projects/${encodeURIComponent(id)}`

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

  // Queue / runs / loops
  getQueue: (id: string) => request<Queue>(`${proj(id)}/queue`),
  listRuns: (id: string, limit = 50, offset = 0) =>
    request<RunsPage>(`${proj(id)}/runs?limit=${limit}&offset=${offset}`),
  getRun: (id: string, stem: string, offset = 0) =>
    request<RunDetail>(`${proj(id)}/runs/${encodeURIComponent(stem)}?offset=${offset}`),
  getLoopState: (id: string, name: string) =>
    request<LoopState>(`${proj(id)}/loops/${encodeURIComponent(name)}/state`),
  getLoopLedger: (id: string, name: string) =>
    request<LoopLedger>(`${proj(id)}/loops/${encodeURIComponent(name)}/ledger`),

  // Health / metrics
  getLint: (id: string) => request<LintResult>(`${proj(id)}/lint`),
  getEngines: (id: string) => request<EngineInfo[]>(`${proj(id)}/engines`),
  getScorecard: (id: string) => request<ScorecardTotals>(`${proj(id)}/scorecard`),

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
