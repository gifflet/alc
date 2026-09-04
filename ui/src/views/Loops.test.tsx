import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Loops } from './Loops'
import { uiStore } from '../app/uiStore'
import { execStore } from '../app/execStore'
import { installFetch, renderWithProviders } from '../test/utils'
import type { LoopState, WorktreeStatus } from '../api/types'

const loopsList = [{ name: 'deliver', mtime: 0 }]

const loopState: LoopState = {
  name: 'deliver',
  status: 'pending',
  cycle: 0,
  consecutive_no_progress: 0,
  budget_used: {},
  stopped_reason: null,
  definition: {
    replenish_kind: 'plan',
    replenish_ref: 'janitor',
    max_cycles: 10,
    budget_unit: 'usd',
    budget_max: 10,
    drain_concurrency: 1,
  },
}

// A full WorktreeStatus (RepoStatus superset) with the given dirty flag; the
// branch/ahead/behind fields are irrelevant to Loops (it reads only `.dirty`),
// but the shape must be complete now the endpoint returns the enriched status.
function wt(dirty: boolean): WorktreeStatus {
  return {
    available: true,
    dirty,
    branch: 'main',
    detached: false,
    upstream: null,
    ahead: null,
    behind: null,
    untracked: 0,
  }
}

// Route order matters: installFetch matches by substring, first match wins, so
// the specific `/loops/deliver/state` must precede the `/loops` collection list.
function routes(worktree: WorktreeStatus) {
  return {
    '/loops/deliver/state': loopState,
    '/worktree': worktree,
    '/loops': loopsList,
  }
}

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  execStore.reset()
})

describe('Loops', () => {
  it('warns but keeps the run controls enabled when the tree is dirty', async () => {
    installFetch(routes(wt(true)))
    renderWithProviders(<Loops />)

    // The banner sets expectations — it no longer gates the run.
    expect(await screen.findByText(/Working tree not clean/i)).toBeInTheDocument()

    // A dirty tree is safe: the run proceeds, so both controls stay live.
    expect(screen.getByLabelText('Run one cycle of deliver')).not.toBeDisabled()
    expect(screen.getByLabelText('Run loop deliver')).not.toBeDisabled()
  })

  it('renders normally with the run controls enabled when the tree is clean', async () => {
    installFetch(routes(wt(false)))
    renderWithProviders(<Loops />)

    // The row renders and both run controls are live — no block note in sight.
    expect(await screen.findByLabelText('Run one cycle of deliver')).not.toBeDisabled()
    expect(screen.getByLabelText('Run loop deliver')).not.toBeDisabled()
    expect(screen.queryByText(/Working tree not clean/i)).not.toBeInTheDocument()
  })
})

describe('Loops — the row explains itself (finding 41)', () => {
  it('shows what the loop does and when it stops', async () => {
    installFetch(routes(wt(false)))
    renderWithProviders(<Loops />)

    expect(await screen.findByText(/plan via janitor · stops after 10 cycles or \$10/)).toBeInTheDocument()
  })

  it('labels both spend controls with words, not icons alone', async () => {
    installFetch(routes(wt(false)))
    renderWithProviders(<Loops />)

    expect(await screen.findByRole('button', { name: 'Run one cycle of deliver' })).toHaveTextContent('Run once')
    expect(screen.getByRole('button', { name: 'Run loop deliver' })).toHaveTextContent('Run loop')
  })

  it('confirms a cycle before spending, then leaves a receipt', async () => {
    const { userEvent } = await import('@testing-library/user-event').then((m) => ({ userEvent: m.default }))
    installFetch({ ...routes(wt(false)), '/exec': { id: 'e9' } })
    renderWithProviders(<Loops />)

    await userEvent.click(await screen.findByRole('button', { name: 'Run one cycle of deliver' }))
    expect(await screen.findByText(/real engine turns are spent/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Run cycle' }))
    // Receipt on the row AND the screen-level live banner both announce —
    // two status regions, each with its own words.
    expect(await screen.findByText(/Cycle started/)).toBeInTheDocument()
    expect(screen.getByText(/A cycle is executing/)).toBeInTheDocument()
  })

  it('"Not now" dismisses without starting anything', async () => {
    const { userEvent } = await import('@testing-library/user-event').then((m) => ({ userEvent: m.default }))
    const mock = installFetch(routes(wt(false)))
    renderWithProviders(<Loops />)

    await userEvent.click(await screen.findByRole('button', { name: 'Run one cycle of deliver' }))
    await userEvent.click(screen.getByRole('button', { name: 'Not now' }))

    expect(mock.calls.some((c) => c.method === 'POST')).toBe(false)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})

describe('Loops — the pill agrees with reality (finding 45)', () => {
  it('renders a persisted "running" as calm "active" when nothing executes', async () => {
    installFetch({ ...routes(wt(false)), '/loops/deliver/state': { ...loopState, status: 'running', cycle: 1 } })
    renderWithProviders(<Loops />)

    // The state file persists 'running' between cycles — honest for cron,
    // an amber lie as a pulse when no cycle/loop exec is live.
    expect(await screen.findByText('active')).toBeInTheDocument()
    expect(screen.queryByText('running')).not.toBeInTheDocument()
    expect(screen.getByText('active')).toHaveAttribute('title', expect.stringMatching(/between cycles/))
  })

  it('regression: pulses as "running" while a cycle exec is actually live', async () => {
    installFetch({ ...routes(wt(false)), '/loops/deliver/state': { ...loopState, status: 'running', cycle: 1 } })
    execStore.launch({ id: 'c1', projectId: 'demo', command: 'cycle' })
    renderWithProviders(<Loops />)

    expect(await screen.findByText('running')).toBeInTheDocument()
    expect(screen.queryByText('active')).not.toBeInTheDocument()
    expect(screen.getByText(/A cycle is executing/)).toBeInTheDocument()
  })
})
