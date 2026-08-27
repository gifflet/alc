// The provider boundary, exercised for real.
//
// `useWs` throws when there is no WsProvider above it. ProjectSelector calls it
// (cloning and creating a project report progress over the socket), and it is
// mounted on two screens that have no project yet — so it rendered outside the
// provider, threw during render, and React unmounted the tree. A blank page on
// the first run of a fresh install.
//
// Nothing caught it: every test that touches ProjectSelector mocks
// ../ws/WsProvider away, which is right for a unit test and exactly why it
// cannot be the only coverage. These tests render the real chain, so a consumer
// mounted outside a provider fails here instead of in someone's browser.
import { QueryClientProvider, QueryClient } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Authenticated } from './App'
import { installFetch } from '../test/utils'

function renderApp(route: string) {
  // Authenticated owns its own BrowserRouter, so the route is set the way a
  // browser sets it. Driving the real router is the point — a MemoryRouter
  // wrapper would test a tree the app never builds.
  window.history.pushState({}, '', route)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <Authenticated />
    </QueryClientProvider>,
  )
}

let errors: string[] = []

beforeEach(() => {
  localStorage.clear()
  errors = []
  // A render-phase throw surfaces through console.error before the boundary
  // swallows it. Collecting it is what makes "did not crash" a real assertion
  // rather than a hopeful one.
  vi.spyOn(console, 'error').mockImplementation((...args) => {
    errors.push(args.map(String).join(' '))
  })
})

afterEach(() => vi.restoreAllMocks())

describe('the screens that have no project yet', () => {
  it('renders the empty registry without a provider error', async () => {
    // The state of every fresh install: zero projects, and the selector opens
    // by itself because `open` starts true.
    installFetch({ '/projects': [] })
    renderApp('/')

    expect(await screen.findByText(/No project open/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Projects')).toBeInTheDocument())
    expect(errors.join('\n')).not.toMatch(/useWs must be used within a WsProvider/)
  })

  it('renders an unregistered project without a provider error', async () => {
    installFetch({ '/projects': [] })
    renderApp('/projects/gone-42')

    expect(await screen.findByRole("heading", { name: /not registered/i })).toBeInTheDocument()
    expect(errors.join('\n')).not.toMatch(/useWs must be used within a WsProvider/)
  })

  it('fails loudly if a useWs consumer is ever mounted outside a provider again', async () => {
    // The guard, stated as itself: no screen this app can reach may throw the
    // provider error. If a future component calls useWs above the provider,
    // this is where it stops.
    installFetch({ '/projects': [] })
    renderApp('/')

    await screen.findByText(/No project open/)
    const provider = errors.filter((e) => e.includes('must be used within a WsProvider'))
    expect(provider).toEqual([])
  })
})
