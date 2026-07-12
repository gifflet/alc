// utils.tsx — Shared helpers for component tests: providers + a fetch stub.
import { render } from '@testing-library/react'
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

/** A minimal Response-like object for the fetch stub. */
function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => data,
  } as Response
}

type Routes = Record<string, unknown>

/**
 * Install a global.fetch that matches a request URL against a routes map by
 * substring (first match wins). Unmatched URLs resolve to 404.
 */
export function installFetch(routes: Routes): void {
  const entries = Object.entries(routes)
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    for (const [pattern, data] of entries) {
      if (url.includes(pattern)) return jsonResponse(data)
    }
    return jsonResponse({ detail: `no stub for ${url}` }, 404)
  }) as typeof fetch
}
