// utils.tsx — Shared helpers for component tests: providers + a fetch stub.
import { render } from '@testing-library/react'
import { useState } from 'react'
import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProjectProvider } from '../app/ProjectContext'

/** Render `ui` inside a fresh QueryClient + project scope (no retries). */
export function renderWithProviders(ui: ReactElement, projectId = 'demo') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ProjectProvider value={projectId}>{ui}</ProjectProvider>
    </QueryClientProvider>,
  )
}

/**
 * Render a `value`/`onChange`-controlled structured form (ManifestForm,
 * BlueprintForm, FlowForm, LoopForm, …), feeding each `onChange` result back in
 * as the next `value` so sequential field edits accumulate exactly as they do
 * inside SourceEditor's EditorShell (a form never owns its own draft state).
 * `onDoc` additionally observes every emitted raw string, most recent last.
 */
export function renderControlledForm(
  initial: string,
  renderForm: (value: string, onChange: (v: string) => void) => ReactElement,
  onDoc: (raw: string) => void,
) {
  function Controlled() {
    const [value, setValue] = useState(initial)
    return renderForm(value, (v) => {
      setValue(v)
      onDoc(v)
    })
  }
  return render(<Controlled />)
}

/** A minimal Response-like object for the fetch stub. */
function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => data,
  } as Response
}

/** One recorded fetch call, exposed for assertions on mutations. */
export interface FetchCall {
  url: string
  method: string
  body: unknown
}

/** Wrap a status + body so a route handler can return a non-200 response. */
export function res(status: number, body: unknown): { __res: true; status: number; body: unknown } {
  return { __res: true, status, body }
}

type Handler = (call: FetchCall) => unknown
type Routes = Record<string, unknown | Handler>

/** Installed fetch mock: `calls` records every request for assertions. */
export interface FetchMock {
  calls: FetchCall[]
}

/**
 * Install a global.fetch that matches a request URL against a routes map by
 * substring (first match wins). A route value may be plain data (200 JSON), a
 * `res(status, body)` wrapper, or a handler `(call) => data | res(...)`.
 * Unmatched URLs resolve to 404. The returned mock records every call.
 */
export function installFetch(routes: Routes): FetchMock {
  const entries = Object.entries(routes)
  const mock: FetchMock = { calls: [] }
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const method = (init?.method ?? 'GET').toUpperCase()
    let body: unknown = null
    if (init?.body != null) {
      try {
        body = JSON.parse(init.body as string)
      } catch {
        body = init.body
      }
    }
    const call: FetchCall = { url, method, body }
    mock.calls.push(call)
    for (const [pattern, value] of entries) {
      if (!url.includes(pattern)) continue
      const result = typeof value === 'function' ? (value as Handler)(call) : value
      if (result && typeof result === 'object' && (result as { __res?: boolean }).__res) {
        const r = result as { status: number; body: unknown }
        return jsonResponse(r.body, r.status)
      }
      return jsonResponse(result)
    }
    return jsonResponse({ detail: `no stub for ${url}` }, 404)
  }) as typeof fetch
  return mock
}
