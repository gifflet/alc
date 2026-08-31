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

  it('warns when the default engine is the mock no-op', async () => {
    // beforeEach installs mock as the default engine.
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('Engines')).toBeInTheDocument()
    expect(screen.getByText(/no-op/i)).toBeInTheDocument()
  })

  it('does not warn when a real engine is the default', async () => {
    installFetch({
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
        { name: 'mock', type: 'mock', default: false, tiers: {}, healthy: true },
        {
          name: 'claude-code',
          type: 'claude-code',
          default: true,
          tiers: { standard: 'claude-sonnet-4-6' },
          healthy: true,
        },
      ],
      '/loops': [],
    })
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('Engines')).toBeInTheDocument()
    expect(screen.queryByText(/no-op/i)).not.toBeInTheDocument()
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
      '/team': { members: [], mix_health: { stage: null, core: [], secondary: [], by_archetype: [], total_runs: 0, idle_core: [] } },
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
          idle_core: [],
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
          idle_core: [],
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
      '/team': { members: [], mix_health: { stage: null, core: [], secondary: [], by_archetype: [], total_runs: 0, idle_core: [] } },
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

describe('Scorecard history chart', () => {
  it('lets its columns stretch, so percentage-height bars can render', async () => {
    // The bug: with `items-end` each column sized to content, the bar's height:%
    // resolved against zero, and the card showed an empty box. jsdom computes no
    // layout, so the class itself is what this guards.
    installFetch({
      '/scorecard': {
        reports: 1,
        successes: 0,
        failures: 1,
        span_total: 2,
        passes_total: 0,
        streak_total: 0,
        touch_total: 1,
      },
      '/queue': {
        pending: [],
        done: [
          {
            stem: 'r1',
            mtime: 1,
            task: null,
            report: { success: false, scorecard: { span: 2, passes: 0, streak: 0, touch: 1 } },
            retryable: false,
          },
        ],
      },
      '/runs': { runs: [], total: 0 },
      '/engines': [],
      '/loops': [],
    })
    renderWithProviders(<Dashboard />)
    // The chart is fed by a SECOND query (the queue), so wait for the bar itself
    // rather than for the card title.
    const bar = await screen.findByTitle(/r1: span=2/)
    const chart = bar.parentElement!
    expect(chart.className).toContain('items-stretch')
    expect(chart.className).not.toContain('items-end')
  })
})

describe('Dashboard — work that needs a human', () => {
  const withInbox = (items: unknown[]) =>
    installFetch({
      ...dashboardStubs,
      '/inbox': { items, count: items.length },
    })

  it('leads with pending decisions instead of burying them in a rail badge', async () => {
    withInbox([
      {
        kind: 'branch',
        id: 'b1',
        title: 'alc/run-a1b2c3d4',
        reason: 'run work ready to land',
        branch: 'alc/run-a1b2c3d4',
        verified: true,
      },
    ])
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('Needs you (1)')).toBeInTheDocument()
    expect(screen.getByText('alc/run-a1b2c3d4')).toBeInTheDocument()
    expect(screen.getByText('run work ready to land')).toBeInTheDocument()
  })

  it('stays silent when nothing is waiting', async () => {
    withInbox([])
    renderWithProviders(<Dashboard />)
    // Wait for the page to settle on a card that always renders.
    expect(await screen.findByText('Engines')).toBeInTheDocument()
    expect(screen.queryByText(/Needs you/)).not.toBeInTheDocument()
  })

  it('calls an unverified branch unverified, exactly as the Inbox does', async () => {
    withInbox([
      {
        kind: 'branch',
        id: 'b2',
        title: 'alc/run-deadbeef',
        reason: 'run work — checks did not pass, review before landing',
        branch: 'alc/run-deadbeef',
        verified: false,
      },
    ])
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('Needs you (1)')).toBeInTheDocument()
    expect(screen.getByText('unverified')).toBeInTheDocument()
    expect(screen.queryByText('to land')).not.toBeInTheDocument()
  })

  it('counts every waiting item, whatever its kind', async () => {
    withInbox([
      { kind: 'failure', id: 'f1', title: 'chore x', reason: 'failed twice', stem: 's1' },
      { kind: 'branch', id: 'b1', title: 'alc/run-1', reason: 'ready', branch: 'alc/run-1', verified: true },
      { kind: 'loop', id: 'l1', title: 'nightly', reason: 'halted by a backstop', loop: 'nightly' },
    ])
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('Needs you (3)')).toBeInTheDocument()
  })

  it('opens the Inbox rather than duplicating Land and Discard', async () => {
    withInbox([
      { kind: 'branch', id: 'b1', title: 'alc/run-1', reason: 'ready', branch: 'alc/run-1', verified: true },
    ])
    renderWithProviders(<Dashboard />)
    const card = (await screen.findByText('Needs you (1)')).closest('section')!
    expect(within(card).queryByText('Land')).not.toBeInTheDocument()
    expect(within(card).queryByText('Discard')).not.toBeInTheDocument()
    await userEvent.click(within(card).getByRole('button', { name: 'Open Inbox' }))
    expect(uiStore.getState().tabs.some((t) => t.title === 'Inbox')).toBe(true)
  })
})

describe('Dashboard — telling recent runs apart', () => {
  const withRuns = (runs: unknown[]) => installFetch({ ...dashboardStubs, '/runs': { runs, total: runs.length } })

  it('leads each row with the task, not the stem', async () => {
    withRuns([
      {
        stem: '20260830T041713-run-chore-in-docs-site-scripts-dist-install-e40d96',
        kind: 'run',
        title: 'Fix the closing advice install.sh prints after an upgrade',
        unit: 'chore',
        mtime: 1783828795,
        size: 712,
        finished: true,
        stale: false,
      },
    ])
    renderWithProviders(<Dashboard />)
    const task = await screen.findByText('Fix the closing advice install.sh prints after an upgrade')
    const stem = screen.getByText(/20260830T041713-run-chore-in-docs-site/)
    // The stem is still there as the address — below the task, not instead of it.
    expect(task.compareDocumentPosition(stem) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('tells apart two runs whose stems share a prefix', async () => {
    withRuns([
      { stem: '20260830T041713-run-chore-fix-the-install-a1', kind: 'run', title: 'fix the install banner', unit: 'chore', mtime: 1783828795, size: 1, finished: true, stale: false },
      { stem: '20260830T041714-run-chore-fix-the-install-b2', kind: 'run', title: 'fix the install exit code', unit: 'chore', mtime: 1783828796, size: 1, finished: true, stale: false },
    ])
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('fix the install banner')).toBeInTheDocument()
    expect(screen.getByText('fix the install exit code')).toBeInTheDocument()
  })

  it('falls back to the stem when a run has no task recorded', async () => {
    withRuns([
      { stem: '20260830T041713-run-chore-untitled-a1', kind: 'run', title: '', unit: '', mtime: 1783828795, size: 1, finished: true, stale: false },
    ])
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('20260830T041713-run-chore-untitled-a1')).toBeInTheDocument()
  })

  it('still opens the run it names', async () => {
    withRuns([
      { stem: '20260830T041713-run-chore-x-a1', kind: 'run', title: 'fix it', unit: 'chore', mtime: 1783828795, size: 1, finished: true, stale: false },
    ])
    renderWithProviders(<Dashboard />)
    await userEvent.click(await screen.findByText('fix it'))
    expect(uiStore.getState().tabs.some((t) => t.title === '20260830T041713-run-chore-x-a1')).toBe(true)
  })
})

describe('Dashboard — the numbers explain themselves', () => {
  it('says which direction is good, where a touch screen can read it', async () => {
    renderWithProviders(<Dashboard />)
    // The card header renders before its query resolves; wait for the grid.
    expect(await screen.findByText('reports')).toBeInTheDocument()
    // A hover title is invisible on a phone, and half this project's use is one.
    expect(
      screen.getByText(/Span and streak: higher is better\. Passes and touch: lower is better/),
    ).toBeInTheDocument()
  })

  it('defines each invented word on hover', async () => {
    renderWithProviders(<Dashboard />)
    const span = (await screen.findByText('span')).closest('div')!
    expect(span.getAttribute('title')).toMatch(/checks that passed/i)
    expect(screen.getByText('touch').closest('div')!.getAttribute('title')).toMatch(/human/i)
    expect(screen.getByText('passes').closest('div')!.getAttribute('title')).toMatch(/engine turns/i)
    expect(screen.getByText('streak').closest('div')!.getAttribute('title')).toMatch(/one-shot/i)
  })

  it('explains what declaring a stage would buy, instead of only noting its absence', async () => {
    installFetch({
      ...dashboardStubs,
      '/team': {
        members: [],
        mix_health: { stage: null, core: [], secondary: [], by_archetype: [], total_runs: 3, idle_core: [] },
      },
    })
    renderWithProviders(<Dashboard />)
    // Await the body, not the header — the header renders before the query lands.
    expect(await screen.findByText(/not measured against any target/)).toBeInTheDocument()
    expect(screen.getByText(/how much of your recent work matched/)).toBeInTheDocument()
    // And how to actually do it.
    expect(screen.getByText('pre-pmf')).toBeInTheDocument()
    expect(screen.getByText('.alc/manifest.yaml')).toBeInTheDocument()
  })

  it('still reports the mix once a stage is declared', async () => {
    installFetch({
      ...dashboardStubs,
      '/team': {
        members: [],
        mix_health: {
          stage: 'growth',
          core: ['builder', 'sweeper', 'grower'],
          secondary: ['maintainer'],
          by_archetype: [{ archetype: 'builder', runs: 3, cost_usd: 0.0 }],
          total_runs: 3,
          idle_core: [],
        },
      },
    })
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('growth')).toBeInTheDocument()
    expect(screen.queryByText(/not measured against any target/)).not.toBeInTheDocument()
  })
})
