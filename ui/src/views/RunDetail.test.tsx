import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { artifactFileUrl } from '../api/client'
import { installFetch, renderWithProviders } from '../test/utils'

// RunDetail tails via useWs; a stub client is enough (no live socket in jsdom).
vi.mock('../ws/WsProvider', () => ({
  useWs: () => ({ client: { on: () => () => {} }, status: 'open' }),
}))

import { RunDetail } from './RunDetail'

const events = [
  { ts: '2026-07-12T03:59:55.356Z', event: 'mandate_started', blueprint: 'chore', task: 'exec via API', engine: 'mock', model: 'mock-small' },
  { ts: '2026-07-12T03:59:55.363Z', event: 'act_started', attempt: 0 },
  { ts: '2026-07-12T03:59:55.363Z', event: 'act_finished', attempt: 0, ok: true },
  { ts: '2026-07-12T03:59:55.363Z', event: 'verify_started', attempt: 0, checks: ['smoke'] },
  { ts: '2026-07-12T03:59:55.367Z', event: 'check_finished', attempt: 0, name: 'smoke', passed: true, output_tail: '' },
  { ts: '2026-07-12T03:59:55.373Z', event: 'mandate_finished', success: true, attempts: 1, scorecard: { span: 1, passes: 1, streak: 1, touch: 0 } },
]

beforeEach(() => {
  installFetch({ '/runs/': { events, next_offset: 6 } })
})

describe('RunDetail', () => {
  it('renders the timeline and final scorecard for a finished run', async () => {
    renderWithProviders(<RunDetail stem="20260712T0359-run-chore-x" />)
    // Header title from mandate_started (the blueprint also labels the timeline group).
    expect(await screen.findByRole('heading', { name: 'chore' })).toBeInTheDocument()
    // Timeline Act phase pill.
    expect(screen.getByText('Act')).toBeInTheDocument()
    // Final success pill + scorecard metric labels.
    expect(screen.getByText('success')).toBeInTheDocument()
    expect(screen.getByText('span')).toBeInTheDocument()
    // Event feed formats a check line.
    expect(screen.getByText(/Check smoke passed/)).toBeInTheDocument()
  })

  it('shows stale (not live) for an interrupted run flagged by the backend', async () => {
    const partial = [
      { ts: '2026-07-13T02:15:44Z', event: 'flow_started', flow: 'demand', task: 'fix it' },
      { ts: '2026-07-13T02:16:00Z', event: 'stage_started', stage: 'implement' },
      { ts: '2026-07-13T02:16:01Z', event: 'mandate_started', blueprint: 'dev' },
    ]
    installFetch({ '/runs/': { events: partial, next_offset: 3, stale: true } })
    renderWithProviders(<RunDetail stem="20260713T0215-unit-demand-fix" />)
    expect(await screen.findByText('stale')).toBeInTheDocument()
    expect(screen.queryByText('live')).not.toBeInTheDocument()
  })
})

describe('RunDetail check-config callout', () => {
  it('omits the callout when no check config was touched', async () => {
    installFetch({ '/runs/': { events, next_offset: 6 } })
    renderWithProviders(<RunDetail stem="20260712T0359-run-chore-x" />)
    expect(await screen.findByRole('heading', { name: 'chore' })).toBeInTheDocument()
    expect(screen.queryByText(/modified check-defining config/)).not.toBeInTheDocument()
  })

  it('renders the callout with the touched files when a check_config_edited event is present', async () => {
    const edited = [
      ...events.slice(0, 5),
      { ts: '2026-07-12T03:59:55.370Z', event: 'check_config_edited', files: ['eslint.config.mjs (check config)'] },
      events[5],
    ]
    installFetch({ '/runs/': { events: edited, next_offset: 7 } })
    renderWithProviders(<RunDetail stem="20260712T0359-run-chore-x" />)
    expect(await screen.findByText(/review before trusting the result/)).toBeInTheDocument()
    expect(screen.getAllByText('eslint.config.mjs (check config)').length).toBeGreaterThan(0)
  })
})

describe('RunDetail evidence panel', () => {
  const stem = '20260712T0359-run-chore-x'

  it('does not render when the run has no artifacts', async () => {
    installFetch({
      [`/runs/${stem}/artifacts`]: { stem, artifacts: [] },
      '/runs/': { events, next_offset: 6 },
    })
    renderWithProviders(<RunDetail stem={stem} />)

    expect(await screen.findByRole('heading', { name: 'chore' })).toBeInTheDocument()
    expect(screen.queryByText('Evidence')).not.toBeInTheDocument()
  })

  it('lists each artifact with its type and a link to the exact path it was given', async () => {
    const path = '.alc/artifacts/20260712T0359-run-chore-x/golden.html'
    installFetch({
      [`/runs/${stem}/artifacts`]: { stem, artifacts: [{ path, type: 'data' }] },
      '/runs/': { events, next_offset: 6 },
    })
    renderWithProviders(<RunDetail stem={stem} />)

    expect(await screen.findByText('Evidence')).toBeInTheDocument()
    expect(screen.getByText('data')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: path })
    // The href round-trips the exact `path` string from the list — never rewritten.
    expect(link).toHaveAttribute('href', artifactFileUrl('demo', path))
  })
})
