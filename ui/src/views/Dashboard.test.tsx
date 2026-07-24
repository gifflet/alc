import { beforeEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Dashboard } from './Dashboard'
import { installFetch, renderWithProviders } from '../test/utils'
import type { FetchCall } from '../test/utils'
import { uiStore } from '../app/uiStore'

const dashboardStubs = {
  '/scorecard': {
    reports: 0,
    successes: 0,
    failures: 0,
    span_total: 0,
    passes_total: 0,
    streak_total: 0,
    touch_total: 0,
  },
  '/queue': { pending: [], done: [] },
  '/runs': { runs: [], total: 0 },
  '/engines': [
    { name: 'mock', type: 'mock', default: true, tiers: { standard: 'mock-small' }, healthy: true },
  ],
  '/loops': [],
}

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

  it('renders net lines and a warnings indicator when the scorecard reports them', async () => {
    installFetch({
      '/scorecard': {
        reports: 2,
        successes: 2,
        failures: 0,
        span_total: 3,
        passes_total: 3,
        streak_total: 2,
        touch_total: 0,
        net_lines_total: -142,
        runs_with_warnings: 2,
      },
      '/queue': { pending: [], done: [] },
      '/runs': { runs: [], total: 0 },
      '/engines': [
        { name: 'mock', type: 'mock', default: true, tiers: { standard: 'mock-small' }, healthy: true },
      ],
      '/loops': [],
    })
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('net lines')).toBeInTheDocument()
    expect(screen.getByText('−142')).toBeInTheDocument()
    expect(screen.getByText('2 runs with warnings')).toBeInTheDocument()
  })

  it('renders net lines as neutral and hides the warnings indicator when the backend omits them', async () => {
    // The default beforeEach stub predates net_lines_total/runs_with_warnings —
    // an older backend must not break the card.
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('net lines')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryByText(/with warnings/)).not.toBeInTheDocument()
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

describe('Mix Health card', () => {
  it('shows "no data" when total_runs is 0', async () => {
    installFetch({
      ...dashboardStubs,
      '/team': { members: [], mix_health: { stage: null, core: [], secondary: [], by_archetype: [], total_runs: 0 } },
    })
    renderWithProviders(<Dashboard />)

    expect(await screen.findByText('Mix Health')).toBeInTheDocument()
    expect(screen.getByText(/no data yet/i)).toBeInTheDocument()
  })

  it('shows "no stage" when the project declares none, even with archived runs', async () => {
    installFetch({
      ...dashboardStubs,
      '/team': {
        members: [],
        mix_health: {
          stage: null,
          core: [],
          secondary: [],
          by_archetype: [{ archetype: 'builder', runs: 2, span: 4, cost_usd: 1.5, net_lines: 12 }],
          total_runs: 2,
        },
      },
    })
    renderWithProviders(<Dashboard />)

    expect(await screen.findByText(/no stage declared/i)).toBeInTheDocument()
  })

  it('summarises core/secondary/off-mix runs against the declared stage', async () => {
    installFetch({
      ...dashboardStubs,
      '/team': {
        members: [],
        mix_health: {
          stage: 'growth',
          core: ['builder'],
          secondary: ['maintainer'],
          by_archetype: [
            { archetype: 'builder', runs: 3, span: 6, cost_usd: 0.9, net_lines: 20 },
            { archetype: 'prototyper', runs: 1, span: 1, cost_usd: 0.1, net_lines: -5 },
          ],
          total_runs: 4,
        },
      },
    })
    renderWithProviders(<Dashboard />)

    expect(await screen.findByText(/growth/)).toBeInTheDocument()
    expect(screen.getByText('core')).toBeInTheDocument()
    expect(screen.getByText('off-mix')).toBeInTheDocument()
  })

  it('opens the Team view from the card action', async () => {
    installFetch({
      ...dashboardStubs,
      '/team': { members: [], mix_health: { stage: null, core: [], secondary: [], by_archetype: [], total_runs: 0 } },
    })
    renderWithProviders(<Dashboard />)

    const card = (await screen.findByText('Mix Health')).closest('section') as HTMLElement
    await userEvent.click(within(card).getByText('open'))
    expect(uiStore.getState().activeTabId).toBe('view:team')
  })
})

describe('Schedule card', () => {
  it('shows the "no crontab" state when the host has none', async () => {
    installFetch({ ...dashboardStubs, '/schedule': { available: false, entries: [] } })
    renderWithProviders(<Dashboard />)

    expect(await screen.findByText('Schedule')).toBeInTheDocument()
    expect(await screen.findByText('No crontab on this host.')).toBeInTheDocument()
  })

  it('shows an empty state when the crontab has no ALC-scheduled entries', async () => {
    installFetch({ ...dashboardStubs, '/schedule': { available: true, entries: [] } })
    renderWithProviders(<Dashboard />)

    expect(await screen.findByText('Schedule')).toBeInTheDocument()
    expect(await screen.findByText('No ALC-scheduled entries.')).toBeInTheDocument()
  })

  it('lists the alc-schedule entries the backend returns', async () => {
    const tickEntry = '*/15 * * * * cd /proj && /usr/bin/alc tick # alc-schedule:tick'
    const cycleEntry =
      '0 */2 * * * cd /proj && /usr/bin/alc cycle deliver # alc-schedule:cycle:deliver'
    installFetch({
      ...dashboardStubs,
      '/schedule': { available: true, entries: [tickEntry, cycleEntry] },
    })
    renderWithProviders(<Dashboard />)

    expect(await screen.findByText(tickEntry)).toBeInTheDocument()
    expect(screen.getByText(cycleEntry)).toBeInTheDocument()
    expect(screen.getByText(/install or remove a schedule with/i)).toBeInTheDocument()
  })
})

describe('Audit card', () => {
  const auditWindow = (overrides: { tasks_total: number; cost_usd_total: number }) => ({
    since_epoch: 0,
    tasks_total: overrides.tasks_total,
    tasks_ok: overrides.tasks_total,
    tasks_failed: 0,
    span_total: 0,
    span_avg: 0,
    passes_total: 0,
    passes_avg: 0,
    streak_total: 0,
    streak_avg: 0,
    touch_total: 0,
    touch_avg: 0,
    changed_files_total: 0,
    input_tokens_total: 0,
    output_tokens_total: 0,
    cost_usd_total: overrides.cost_usd_total,
  })

  it('defaults to the 7d window, then refetches the newly selected window', async () => {
    const mock = installFetch({
      ...dashboardStubs,
      '/audit': (call: FetchCall) =>
        call.url.includes('since=24h')
          ? auditWindow({ tasks_total: 2, cost_usd_total: 1 })
          : auditWindow({ tasks_total: 5, cost_usd_total: 12.5 }),
    })
    renderWithProviders(<Dashboard />)

    expect(await screen.findByText('Audit')).toBeInTheDocument()
    expect(await screen.findByText('$12.50')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Audit window' }), '24h')

    expect(await screen.findByText('$1.00')).toBeInTheDocument()
    expect(
      mock.calls.some((c) => c.method === 'GET' && c.url.includes('/audit') && c.url.includes('since=24h')),
    ).toBe(true)
  })

  it('shows a clear empty state when the window has no archived tasks', async () => {
    installFetch({ ...dashboardStubs, '/audit': auditWindow({ tasks_total: 0, cost_usd_total: 0 }) })
    renderWithProviders(<Dashboard />)

    expect(await screen.findByText(/no archived tasks in this window/i)).toBeInTheDocument()
  })
})
