import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router'
import { UrlSync, useUrlHydration } from './urlSync'
import { uiStore } from './uiStore'

function Harness({ id }: { id: string }) {
  const hydrated = useUrlHydration(id)
  return <UrlSync id={id} hydrated={hydrated} />
}

/** Let the hydration -> setState -> UrlSync effect chain settle a few times. */
async function flush(times = 4) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await Promise.resolve()
    })
  }
}

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

afterEach(() => {
  vi.restoreAllMocks()
  window.history.replaceState({}, '', '/')
})

const cases: { path: string; tabId: string }[] = [
  { path: '/projects/demo', tabId: 'view:dashboard' },
  { path: '/projects/demo/queue', tabId: 'view:queue' },
  { path: '/projects/demo/runs/20260712T0359-run-x', tabId: 'run:20260712T0359-run-x' },
  { path: '/projects/demo/loops/nightly', tabId: 'loop:nightly' },
  { path: '/projects/demo/config/manifest', tabId: 'source:manifest:manifest' },
  { path: '/projects/demo/config/blueprints/chore', tabId: 'source:blueprints:chore' },
]

describe('deep-link hydration', () => {
  it.each(cases)('opens the $tabId tab without a navigation loop ($path)', async ({ path, tabId }) => {
    window.history.replaceState({}, '', path)
    const spy = vi.spyOn(window.history, 'replaceState')

    render(
      <BrowserRouter>
        <Harness id="demo" />
      </BrowserRouter>,
    )

    // The deep-linked tab becomes active.
    await waitFor(() => expect(uiStore.getState().activeTabId).toBe(tabId))

    // No ping-pong: the replaceState count settles small and stops growing.
    await flush()
    const settled = spy.mock.calls.length
    await flush()
    expect(spy.mock.calls.length).toBe(settled)
    // The URL already matched the active tab, so UrlSync adds no navigation.
    expect(settled).toBeLessThanOrEqual(1)
    expect(window.location.pathname).toBe(path)
  })
})

describe('store -> URL after mount', () => {
  it('reflects a tab opened in-app and does not re-hydrate', async () => {
    window.history.replaceState({}, '', '/projects/demo')
    render(
      <BrowserRouter>
        <Harness id="demo" />
      </BrowserRouter>,
    )
    await waitFor(() => expect(uiStore.getState().activeTabId).toBe('view:dashboard'))

    // Open a run tab as a user would; UrlSync mirrors it into the URL.
    await act(async () => {
      uiStore.openTab({ target: { type: 'run', stem: 'abc' }, title: 'abc' })
    })
    await waitFor(() => expect(window.location.pathname).toBe('/projects/demo/runs/abc'))

    // Hydration must not re-run and clobber the just-opened tab.
    await flush()
    expect(uiStore.getState().activeTabId).toBe('run:abc')
  })
})
