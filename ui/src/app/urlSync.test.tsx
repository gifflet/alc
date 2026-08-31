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

describe('system back walks the app history (mobile swipe-back)', () => {
  // The defect: every navigation used `replace: true`, so the whole app lived
  // in ONE history entry and Android's back gesture exited the page. Opening a
  // run from the Runs list and swiping back closed the app instead of
  // returning to the list.

  it('pushes a history entry per navigation instead of replacing', async () => {
    window.history.replaceState({}, '', '/projects/demo/runs')
    render(
      <BrowserRouter>
        <Harness id="demo" />
      </BrowserRouter>,
    )
    await flush()
    const before = window.history.length

    act(() => {
      uiStore.openTab({ target: { type: 'run', stem: '20260712T0359-run-x' }, title: 'run-x' })
    })
    await flush()

    expect(window.location.pathname).toBe('/projects/demo/runs/20260712T0359-run-x')
    expect(window.history.length).toBe(before + 1)
  })

  it('a pop returns to the previous view and refocuses its tab', async () => {
    window.history.replaceState({}, '', '/projects/demo/runs')
    render(
      <BrowserRouter>
        <Harness id="demo" />
      </BrowserRouter>,
    )
    await flush()
    act(() => {
      uiStore.openTab({ target: { type: 'run', stem: '20260712T0359-run-x' }, title: 'run-x' })
    })
    await flush()

    // The Android swipe-back reaches the app as a history pop. jsdom's own
    // history.back() does not reliably fire through a mounted router, so the
    // pop is delivered the way the browser delivers it: location moved, then
    // a popstate event.
    await act(async () => {
      window.history.replaceState({}, '', '/projects/demo/runs')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    await flush()

    expect(window.location.pathname).toBe('/projects/demo/runs')
    expect(uiStore.getState().activeTabId).toBe('view:runs')
  })

  it('the pop side never duplicates a tab', async () => {
    window.history.replaceState({}, '', '/projects/demo/runs')
    render(
      <BrowserRouter>
        <Harness id="demo" />
      </BrowserRouter>,
    )
    await flush()
    act(() => {
      uiStore.openTab({ target: { type: 'run', stem: '20260712T0359-run-x' }, title: 'run-x' })
    })
    await flush()
    const tabsBefore = uiStore.getState().tabs.length

    await act(async () => {
      window.history.replaceState({}, '', '/projects/demo/runs')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    await flush()

    expect(uiStore.getState().tabs.length).toBe(tabsBefore)
  })

  it('our own push does not re-hydrate the store (no ping-pong)', async () => {
    window.history.replaceState({}, '', '/projects/demo')
    render(
      <BrowserRouter>
        <Harness id="demo" />
      </BrowserRouter>,
    )
    await flush()
    const openSpy = vi.spyOn(uiStore, 'openTab')

    act(() => {
      uiStore.openTab({ target: { type: 'view', view: 'queue' }, title: 'Queue', closable: false })
    })
    await flush()

    // Exactly the one call above — the location change it caused must not
    // trigger a second openTab from the pop side.
    expect(openSpy).toHaveBeenCalledTimes(1)
    expect(window.location.pathname).toBe('/projects/demo/queue')
  })

  it('hydration normalisation still replaces, so back is not trapped', async () => {
    // An unknown path hydrates to the dashboard; that correction must not mint
    // an extra entry the back gesture would step through before leaving.
    window.history.replaceState({}, '', '/projects/demo/definitely-not-a-view')
    const before = window.history.length
    render(
      <BrowserRouter>
        <Harness id="demo" />
      </BrowserRouter>,
    )
    await flush()

    expect(window.location.pathname).toBe('/projects/demo')
    expect(window.history.length).toBe(before)
  })
})
