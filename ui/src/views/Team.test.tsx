import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Team } from './Team'
import { installFetch, renderWithProviders } from '../test/utils'
import { uiStore } from '../app/uiStore'
import type { TeamRoster } from '../api/types'

const emptyHealth = { stage: null, core: [], secondary: [], by_archetype: [], total_runs: 0 }

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
      },
    }
    installFetch({ '/team': roster })
    renderWithProviders(<Team />)

    expect(await screen.findByText(/no stage declared/i)).toBeInTheDocument()
    expect(screen.getByText('builder')).toBeInTheDocument()
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
      },
    }
    installFetch({ '/team': roster })
    renderWithProviders(<Team />)

    expect(await screen.findByText('growth')).toBeInTheDocument()
    expect(screen.getByText('[core]')).toBeInTheDocument()
    expect(screen.getByText('[off-mix]')).toBeInTheDocument()
  })
})
