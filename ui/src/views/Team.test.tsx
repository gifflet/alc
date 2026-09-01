import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Team } from './Team'
import { installFetch, renderWithProviders } from '../test/utils'
import { uiStore } from '../app/uiStore'
import type { TeamRoster } from '../api/types'

const emptyHealth = {
  stage: null,
  core: [],
  secondary: [],
  by_archetype: [],
  total_runs: 0,
  idle_core: [],
}

/** sweeper is the honest fixture for retire: its pack really does ship a loop,
 *  so archiving one is a thing that can happen. The old tests retired `builder`
 *  and asserted a moved sweep.yaml — builder ships no loops at all, so that was
 *  a scenario the backend could never produce. */
const memberWithALoop: TeamRoster = {
  members: [
    {
      archetype: 'sweeper',
      files: ['.alc/blueprints/map.md', '.alc/loops/sweep.yaml'],
      loops: [{ name: 'sweep', status: 'pending', cycle: 0, stopped_reason: null }],
    },
  ],
  mix_health: emptyHealth,
}

const oneHiredMember: TeamRoster = {
  members: [
    {
      archetype: 'builder',
      files: ['.alc/blueprints/test.md', '.alc/blueprints/qa.md', '.alc/flows/ship-hardened.yaml'],
      loops: [],
    },
  ],
  mix_health: emptyHealth,
}

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

describe('Team roster', () => {
  it('renders a hired member with its files and offers to hire the rest', async () => {
    installFetch({ '/team': oneHiredMember })
    renderWithProviders(<Team />)

    expect(await screen.findByText('builder')).toBeInTheDocument()
    expect(screen.getByText('.alc/blueprints/test.md')).toBeInTheDocument()
    expect(screen.getByText('.alc/flows/ship-hardened.yaml')).toBeInTheDocument()

    // The four archetypes not yet hired each get a hire button; builder does not.
    expect(screen.getByRole('button', { name: 'Hire sweeper' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hire maintainer' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hire grower' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hire prototyper' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Hire builder' })).not.toBeInTheDocument()
  })

  it('renders a member with zero loops cleanly, with no loops section', async () => {
    installFetch({ '/team': oneHiredMember })
    renderWithProviders(<Team />)

    expect(await screen.findByText('builder')).toBeInTheDocument()
    expect(screen.queryByText(/cycle \d/)).not.toBeInTheDocument()
  })

  it("renders a member's loop and its state", async () => {
    const roster: TeamRoster = {
      members: [
        {
          archetype: 'sweeper',
          files: ['.alc/loops/sweep.yaml'],
          loops: [{ name: 'sweep', status: 'running', cycle: 3, stopped_reason: null }],
        },
      ],
      mix_health: emptyHealth,
    }
    installFetch({ '/team': roster })
    renderWithProviders(<Team />)

    expect(await screen.findByText('sweep')).toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
    expect(screen.getByText('cycle 3')).toBeInTheDocument()
  })

  it('shows an empty roster message when nothing is hired yet', async () => {
    installFetch({ '/team': { members: [], mix_health: emptyHealth } })
    renderWithProviders(<Team />)

    expect(await screen.findByText(/no archetypes hired/i)).toBeInTheDocument()
    // All five hire buttons are offered.
    expect(screen.getByRole('button', { name: 'Hire builder' })).toBeInTheDocument()
  })
})

describe('Team hire', () => {
  it('fires a hire request for the clicked archetype', async () => {
    const mock = installFetch({
      '/team/hire': { written: ['.alc/specialists/janitor.yaml'], lint: { violations: [] } },
      '/team': oneHiredMember,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Hire sweeper' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/team/hire'))
    expect(post?.body).toEqual({ archetype: 'sweeper', force: false })
  })
})

describe('Team retire', () => {
  it('retires a member only after confirmation', async () => {
    const mock = installFetch({
      '/team/retire': { moved: ['.alc/loops/retired/sweep.yaml'] },
      '/team': memberWithALoop,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Retire sweeper' }))

    // The confirmation copy makes clear this archives loops, not deletes them.
    expect(await screen.findByText(/archives/i)).toBeInTheDocument()

    // The mutation must not fire before the confirm dialog is accepted.
    expect(
      mock.calls.some((c) => c.method === 'POST' && c.url.endsWith('/team/retire')),
    ).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Retire' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/team/retire'))
    expect(post?.body).toEqual({ archetype: 'sweeper' })
  })

  it('cancelling the confirm dialog never fires the mutation', async () => {
    const mock = installFetch({
      '/team/retire': { moved: [] },
      '/team': memberWithALoop,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Retire sweeper' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(
      mock.calls.some((c) => c.method === 'POST' && c.url.endsWith('/team/retire')),
    ).toBe(false)
    expect(screen.queryByRole('button', { name: 'Retire' })).not.toBeInTheDocument()
  })
})

describe('Team Mix Health', () => {
  it('shows a clear "no data yet" when total_runs is 0', async () => {
    installFetch({ '/team': { members: [], mix_health: emptyHealth } })
    renderWithProviders(<Team />)

    expect(await screen.findByText(/no data yet/i)).toBeInTheDocument()
  })

  it('shows the plain, unjudged breakdown when no stage is declared', async () => {
    const roster: TeamRoster = {
      members: [],
      mix_health: {
        stage: null,
        core: [],
        secondary: [],
        by_archetype: [{ archetype: 'builder', runs: 2, span: 4, cost_usd: 1.5, net_lines: 12 }],
        total_runs: 2,
        idle_core: [],
      },
    }
    installFetch({ '/team': roster })
    renderWithProviders(<Team />)

    expect(await screen.findByText(/no stage declared/i)).toBeInTheDocument()
    // 'builder' now also names the Hire row (the hire list shares the roster's
    // row anatomy), so the bare-name query legitimately matches twice.
    expect(screen.getAllByText('builder').length).toBeGreaterThan(0)
    // Unjudged: no core/secondary/off-mix labels.
    expect(screen.queryByText('[core]')).not.toBeInTheDocument()
    expect(screen.queryByText('[off-mix]')).not.toBeInTheDocument()
  })

  it('labels core, secondary and off-mix archetypes when a stage is declared', async () => {
    const roster: TeamRoster = {
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
    }
    installFetch({ '/team': roster })
    renderWithProviders(<Team />)

    expect(await screen.findByText('growth')).toBeInTheDocument()
    expect(screen.getByText('[core]')).toBeInTheDocument()
    expect(screen.getByText('[off-mix]')).toBeInTheDocument()
  })

  it('lists an idle-core row: hired-but-idle exercises, not-hired hires', async () => {
    const roster: TeamRoster = {
      members: [],
      mix_health: {
        stage: 'strong-pmf',
        core: ['sweeper', 'grower', 'maintainer'],
        secondary: ['builder'],
        by_archetype: [{ archetype: 'sweeper', runs: 2, span: 4, cost_usd: 0.5, net_lines: 3 }],
        total_runs: 2,
        idle_core: [
          {
            archetype: 'maintainer',
            hired: true,
            hint: 'run its loop (alc loop deps-refresh)',
          },
          { archetype: 'grower', hired: false, hint: 'alc team hire grower' },
        ],
      },
    }
    installFetch({ '/team': roster })
    renderWithProviders(<Team />)

    // Hired-but-idle: told to EXERCISE it, with the loop hint.
    expect(await screen.findByText(/hired but never exercised/)).toBeInTheDocument()
    expect(screen.getByText(/alc loop deps-refresh/)).toBeInTheDocument()
    // Not hired: told to hire it.
    expect(screen.getByText(/not hired/)).toBeInTheDocument()
    expect(screen.getByText(/alc team hire grower/)).toBeInTheDocument()
  })
})

describe('Team retire — saying what happened', () => {
  it('does not offer retire to a member that has no loops', async () => {
    // builder ships zero loops, so retire could only ever return moved: [] —
    // a 200 that changes nothing, which read as a broken app.
    installFetch({ '/team': oneHiredMember })
    renderWithProviders(<Team />)

    const button = await screen.findByRole('button', { name: 'Retire builder' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', expect.stringMatching(/no loops on disk/i))
  })

  it('reports what was archived, and that the member stays', async () => {
    installFetch({
      '/team/retire': { moved: ['.alc/loops/retired/sweep.yaml'] },
      '/team': memberWithALoop,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Retire sweeper' }))
    await userEvent.click(screen.getByRole('button', { name: 'Retire' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/Archived 1 loop/)
    expect(status).toHaveTextContent(/stays on the roster/)
  })

  it('says so when there was nothing to archive', async () => {
    // The CLI prints "'x' has no loop(s) on disk to retire." The UI used to
    // print nothing at all and close the dialog.
    installFetch({ '/team/retire': { moved: [] }, '/team': memberWithALoop })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Retire sweeper' }))
    await userEvent.click(screen.getByRole('button', { name: 'Retire' }))

    expect(await screen.findByRole('status')).toHaveTextContent(/nothing to archive/i)
  })

  it('warns in the confirm that the member is not removed', async () => {
    installFetch({ '/team': memberWithALoop })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Retire sweeper' }))
    expect(await screen.findByText(/STAYS on the roster/)).toBeInTheDocument()
  })
})
