import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Dashboard } from './Dashboard'
import { installFetch, renderWithProviders } from '../test/utils'
import { uiStore } from '../app/uiStore'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  installFetch({
    '/scorecard': {
      reports: 2,
      successes: 2,
      failures: 0,
      span_total: 3,
      passes_total: 3,
      streak_total: 2,
      touch_total: 0,
    },
    '/queue': { pending: [], done: [] },
    '/runs': {
      runs: [{ stem: '20260712T0359-run-chore-x', kind: 'run', mtime: 1783828795, size: 712, finished: true }],
      total: 1,
    },
    '/engines': [
      { name: 'mock', type: 'mock', default: true, tiers: { standard: 'mock-small' }, healthy: true },
    ],
    '/loops': [],
  })
})

describe('Dashboard', () => {
  it('renders the engines and recent runs from the API', async () => {
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('Engines')).toBeInTheDocument()
    // 'mock' appears both as the engine name and its type.
    expect(screen.getAllByText('mock').length).toBeGreaterThan(0)
    expect(await screen.findByText('20260712T0359-run-chore-x')).toBeInTheDocument()
    expect(screen.getByText('Recent runs')).toBeInTheDocument()
  })

  it('shows the aggregate scorecard', async () => {
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('Scorecard')).toBeInTheDocument()
    // The "reports" metric appears once the aggregate query resolves.
    expect(await screen.findByText('reports')).toBeInTheDocument()
  })
})
