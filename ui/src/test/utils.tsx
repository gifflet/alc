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

/**
 * Install a matchMedia stub. `matching` lists query fragments that should match
 * (e.g. '(pointer: coarse)'); everything else reports false.
 *
 * jsdom ships no matchMedia, and the production code deliberately treats its
 * absence as "not matching" — which lands on `compact`, today's desktop. Tests
 * that want touch/narrow behaviour must opt in through this helper.
 */
export function mockMatchMedia(matching: string[] = []): void {
  window.matchMedia = ((query: string) =>
    ({
      matches: matching.some((fragment) => query.includes(fragment)),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList) as typeof window.matchMedia
}

/** Remove the matchMedia stub, restoring the "no matchMedia" host default. */
export function clearMatchMedia(): void {
  // @ts-expect-error — deleting an optional host API is the point of the reset.
  delete window.matchMedia
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
  /** Request headers, lower-cased keys — for asserting auth is attached. */
  headers: Record<string, string>
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
    const headers: Record<string, string> = {}
    for (const [k, v] of Object.entries((init?.headers ?? {}) as Record<string, string>)) {
      headers[k.toLowerCase()] = v
    }
    const call: FetchCall = { url, method, body, headers }
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
