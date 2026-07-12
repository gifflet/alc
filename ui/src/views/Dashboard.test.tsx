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

  it('renders per-report history bars when there are done reports', async () => {
    installFetch({
      '/scorecard': {
        reports: 1,
        successes: 1,
        failures: 0,
        span_total: 4,
        passes_total: 4,
        streak_total: 1,
        touch_total: 0,
      },
      '/queue': {
        pending: [],
        done: [
          {
            stem: 'ship-1',
            mtime: 10,
            task: null,
            report: {
              flow: 'ship',
              engine: 'mock',
              success: true,
              stages: [],
              scorecard: { span: 4, passes: 4, streak: 1, touch: 0 },
              commit_sha: null,
            },
          },
        ],
      },
      '/runs': { runs: [], total: 0 },
      '/engines': [{ name: 'mock', type: 'mock', default: true, tiers: {}, healthy: true }],
      '/loops': [],
    })
    renderWithProviders(<Dashboard />)
    expect(await screen.findByTitle(/ship-1: span=4/)).toBeInTheDocument()
  })
})
