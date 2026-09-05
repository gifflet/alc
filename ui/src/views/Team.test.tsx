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
      retired_loops: [],
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
      retired_loops: [],
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
          retired_loops: [],
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

describe('Team archive loops', () => {
  it('retires a member only after confirmation', async () => {
    const mock = installFetch({
      '/team/retire': { moved: ['.alc/loops/retired/sweep.yaml'] },
      '/team': memberWithALoop,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Archive sweeper loops' }))

    // The confirmation copy makes clear this archives loops, not deletes them.
    expect(await screen.findByText(/archives/i)).toBeInTheDocument()

    // The mutation must not fire before the confirm dialog is accepted.
    expect(
      mock.calls.some((c) => c.method === 'POST' && c.url.endsWith('/team/retire')),
    ).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Archive loops' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/team/retire'))
    expect(post?.body).toEqual({ archetype: 'sweeper' })
  })

  it('cancelling the confirm dialog never fires the mutation', async () => {
    const mock = installFetch({
      '/team/retire': { moved: [] },
      '/team': memberWithALoop,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Archive sweeper loops' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(
      mock.calls.some((c) => c.method === 'POST' && c.url.endsWith('/team/retire')),
    ).toBe(false)
    expect(screen.queryByRole('button', { name: 'Archive loops' })).not.toBeInTheDocument()
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

describe('Team archive loops — saying what happened', () => {
  it('shows no archive control at all for a member that has no loops', async () => {
    // builder ships zero loops, so archiving could only ever return moved: []
    // — a 200 that changes nothing. The first fix disabled the button with a
    // tooltip; next to sweeper's "loops archived" badge that rendered one
    // no-loops idea in two different costumes (dogfood: "why is it
    // different?"), and tooltips are unreachable on a phone anyway.
    installFetch({ '/team': oneHiredMember })
    renderWithProviders(<Team />)

    expect(await screen.findByText('builder')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Archive builder loops' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('loops archived')).not.toBeInTheDocument()
    // The exit is still offered.
    expect(screen.getByRole('button', { name: 'Remove builder' })).toBeInTheDocument()
  })

  it('reports what was archived, and that the member stays', async () => {
    installFetch({
      '/team/retire': { moved: ['.alc/loops/retired/sweep.yaml'] },
      '/team': memberWithALoop,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Archive sweeper loops' }))
    await userEvent.click(screen.getByRole('button', { name: 'Archive loops' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/Archived 1 loop/)
    expect(status).toHaveTextContent(/stays on the roster/)
  })

  it('says so when there was nothing to archive', async () => {
    // The CLI prints "'x' has no loop(s) on disk to retire." The UI used to
    // print nothing at all and close the dialog.
    installFetch({ '/team/retire': { moved: [] }, '/team': memberWithALoop })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Archive sweeper loops' }))
    await userEvent.click(screen.getByRole('button', { name: 'Archive loops' }))

    expect(await screen.findByRole('status')).toHaveTextContent(/nothing to archive/i)
  })

  it('warns in the confirm that the member is not removed', async () => {
    installFetch({ '/team': memberWithALoop })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Archive sweeper loops' }))
    expect(await screen.findByText(/stays on the roster/)).toBeInTheDocument()
  })
})

describe('Team archived state', () => {
  const archivedSweeper: TeamRoster = {
    members: [
      {
        archetype: 'sweeper',
        files: ['.alc/blueprints/map.md', '.alc/specialists/janitor.yaml'],
        loops: [],
        retired_loops: ['sweep'],
      },
    ],
    mix_health: emptyHealth,
  }

  it('replaces the dead Archive button with a "loops archived" state', async () => {
    // Post-archive the old UI showed a permanently disabled Retire button and
    // an unchanged roster — which read as a broken app (dogfood: the retire
    // question). A state is the answer, not a control that can never fire.
    installFetch({ '/team': archivedSweeper })
    renderWithProviders(<Team />)

    expect(await screen.findByText('loops archived')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Archive sweeper loops' }),
    ).not.toBeInTheDocument()
  })

  it('lists the archived loop with its location', async () => {
    installFetch({ '/team': archivedSweeper })
    renderWithProviders(<Team />)

    expect(await screen.findByText('sweep')).toBeInTheDocument()
    expect(screen.getByText('archived')).toBeInTheDocument()
    expect(screen.getByText(/loops\/retired\//)).toBeInTheDocument()
  })
})

describe('Team remove', () => {
  it('removes a member only after confirmation', async () => {
    const mock = installFetch({
      '/team/remove': { removed: ['.alc/blueprints/map.md', '.alc/loops/sweep.yaml'], kept: [] },
      '/team': memberWithALoop,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Remove sweeper' }))

    // The confirmation copy promises the safety rule: customised files survive.
    expect(await screen.findByText(/customised is kept/i)).toBeInTheDocument()
    expect(
      mock.calls.some((c) => c.method === 'POST' && c.url.endsWith('/team/remove')),
    ).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/team/remove'))
    expect(post?.body).toEqual({ archetype: 'sweeper' })
  })

  it('reports a full removal and the way back', async () => {
    installFetch({
      '/team/remove': { removed: ['.alc/blueprints/map.md', '.alc/loops/sweep.yaml'], kept: [] },
      '/team': memberWithALoop,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Remove sweeper' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/Removed sweeper \(2 files\)/)
    expect(status).toHaveTextContent(/Hire again anytime/)
  })

  it('reports kept customised files and that the member stays', async () => {
    installFetch({
      '/team/remove': { removed: ['.alc/loops/sweep.yaml'], kept: ['.alc/blueprints/map.md'] },
      '/team': memberWithALoop,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Remove sweeper' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/Kept 1 customised file/)
    expect(status).toHaveTextContent(/.alc\/blueprints\/map.md/)
    expect(status).toHaveTextContent(/stays on the roster/)
  })

  it('cancelling the confirm dialog never fires the mutation', async () => {
    const mock = installFetch({
      '/team/remove': { removed: [], kept: [] },
      '/team': memberWithALoop,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Remove sweeper' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(
      mock.calls.some((c) => c.method === 'POST' && c.url.endsWith('/team/remove')),
    ).toBe(false)
  })
})

describe('Team hire — saying what happened', () => {
  // Finding 33: the CLI prints what a hire wrote and one next action; the UI
  // refreshed the roster in complete silence.
  it('reports the files added, the retarget and the next step', async () => {
    installFetch({
      '/team/hire': {
        written: ['.alc/blueprints/map.md', '.alc/blueprints/refactor.md'],
        kept: [],
        lint: { violations: [] },
        next: 'alc run refactor "<the file or area to clean up>"',
        retargeted: { '.alc/blueprints/refactor.md': 'project' },
      },
      '/team': oneHiredMember,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Hire sweeper' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/Hired sweeper \(2 files added\)/)
    expect(status).toHaveTextContent(/'project' check set/)
    expect(status).toHaveTextContent(/Next: alc run refactor/)
  })

  it('degrades cleanly when the backend omits the new fields', async () => {
    installFetch({
      '/team/hire': { written: ['.alc/specialists/janitor.yaml'], kept: [], lint: { violations: [] } },
      '/team': oneHiredMember,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Hire sweeper' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/Hired sweeper \(1 file added\)/)
  })
})

describe('Team hire — the next step is a tap, not homework', () => {
  it('offers Try it now for an `alc run` next step and preselects the blueprint', async () => {
    installFetch({
      '/team/hire': {
        written: ['.alc/blueprints/refactor.md'],
        kept: [],
        lint: { violations: [] },
        next: 'alc run refactor "<the file or area to clean up>"',
        retargeted: {},
      },
      '/team': oneHiredMember,
    })
    renderWithProviders(<Team />)

    await userEvent.click(await screen.findByRole('button', { name: 'Hire sweeper' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Start work with refactor' }))

    expect(uiStore.getState().pendingBlueprint).toBe('refactor')
    expect(uiStore.getState().activeTabId).toBe('view:dashboard')
  })
})
