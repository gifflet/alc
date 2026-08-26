import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { App, queryClient } from './App'
import { installFetch } from '../test/utils'
import { uiStore } from './uiStore'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  // The App's QueryClient is module-scoped; without this, one case's project
  // list is still cached when the next renders.
  queryClient.clear()
})

/** Render the app at a project URL with a given /api/projects payload. */
function renderAt(path: string, projects: unknown) {
  // Every project-scoped query the shell fires needs a well-SHAPED reply; a
  // blanket {} makes components crash on .filter and hides what is being tested.
  installFetch({
    '/api/projects': projects,
    '/execs': [],
    '/engines': [],
    '/inbox': { items: [], count: 0 },
    '/fleet': { units: [] },
    '/runs': { runs: [], total: 0 },
    '/queue': { pending: [], done: [] },
    '/branches': { available: false, branches: [] },
    '/lint': { violations: [] },
    '/worktree': { dirty: false, files: [] },
    '/blueprints': [],
    '/flows': [],
    '/specialists': [],
    '/loops': [],
    '/primers': [],
    '/prompts': [],
  })
  window.history.pushState({}, '', path)
  return render(<App />)
}

const AVAILABLE = [
  { id: 'demo-1a2b', name: 'demo', path: '/tmp/demo', available: true, queue_pending: 0 },
]

describe('ProjectShell degraded states', () => {
  it('does not render the shell for a project that is not registered', async () => {
    renderAt('/projects/ghost-9z9z/fleet', AVAILABLE)
    expect(await screen.findByText('Project not registered')).toBeInTheDocument()
    // The rail would offer actions against a project the backend 404s for.
    expect(screen.queryByLabelText('Run Configurations')).toBeNull()
    expect(screen.queryByLabelText('Fleet')).toBeNull()
  })

  it('does not render the shell when the project folder is gone', async () => {
    renderAt('/projects/demo-1a2b/fleet', [{ ...AVAILABLE[0], available: false }])
    expect(await screen.findByText('Project unavailable')).toBeInTheDocument()
    expect(screen.queryByLabelText('Run Configurations')).toBeNull()
  })

  it('renders the shell normally for an available project', async () => {
    renderAt('/projects/demo-1a2b/fleet', AVAILABLE)
    expect(await screen.findByLabelText('Run Configurations')).toBeInTheDocument()
    expect(screen.queryByText('Project not registered')).toBeNull()
  })

  it('says nothing about availability while the list is still loading', () => {
    // A flash of "not registered" before the list arrives would be a lie too —
    // and so would rendering the shell and querying an id we cannot vouch for.
    installFetch({})
    window.history.pushState({}, '', '/projects/demo-1a2b/fleet')
    render(<App />)
    expect(screen.queryByText('Project not registered')).toBeNull()
    expect(screen.queryByLabelText('Run Configurations')).toBeNull()
    expect(screen.getByText('Loading project…')).toBeInTheDocument()
  })
})
