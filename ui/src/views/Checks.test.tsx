import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Checks } from './Checks'
import { installFetch, renderWithProviders } from '../test/utils'
import type { CheckHistoryEntry, ChecksAudit, OnboardProposal } from '../api/types'

const history: CheckHistoryEntry[] = [
  { name: 'test', runs: 4, passes: 2, pass_rate: 0.5, mean_duration_s: 1.25, flake_score: 1.0 },
]

const emptyAudit: ChecksAudit = { check_sets: [], smoke_only_blueprints: [] }

// The Checks view now embeds the Onboard panel, so every render fetches the
// proposal too. These specs cover History/Audit — an empty proposal keeps the
// panel out of the way (its own behavior is covered in OnboardPanel.test.tsx).
const emptyOnboard: OnboardProposal = {
  check_sets: {},
  blueprint_opt_ins: {},
  stage: null,
  team_hints: [],
  unknowns: [],
}

const populatedAudit: ChecksAudit = {
  check_sets: [
    {
      set_name: 'python',
      is_new: true,
      add: [['lint', ['ruff', 'check', '.']]],
      unavailable: [['test', ['pytest', '-q']]],
    },
  ],
  smoke_only_blueprints: [{ blueprint: 'chore', stacks: ['Python'] }],
}

// One smoke-only entry with a detected stack and one with none (stacks: []),
// so a single render exercises both branches of the honest phrasing.
const smokeOnlyMixedAudit: ChecksAudit = {
  check_sets: [],
  smoke_only_blueprints: [
    { blueprint: 'refactor', stacks: ['Python'] },
    { blueprint: 'chore', stacks: [] },
  ],
}

describe('Checks', () => {
  it('renders the history table with pass-rate/duration/flake-score', async () => {
    installFetch({
      '/checks/history': history,
      '/checks/audit': emptyAudit,
      '/checks/onboard': emptyOnboard,
    })
    renderWithProviders(<Checks />)

    expect(await screen.findByText('test')).toBeInTheDocument()
    expect(screen.getByText('50% (2/4)')).toBeInTheDocument()
    expect(screen.getByText('1.25s')).toBeInTheDocument()
    expect(screen.getByText('1.00')).toBeInTheDocument()
  })

  it('shows an empty state when there is no run history yet', async () => {
    installFetch({
      '/checks/history': [],
      '/checks/audit': emptyAudit,
      '/checks/onboard': emptyOnboard,
    })
    renderWithProviders(<Checks />)

    expect(await screen.findByText(/no check history yet/i)).toBeInTheDocument()
  })

  it('renders proposed check-set upgrades and smoke-only blueprints', async () => {
    installFetch({
      '/checks/history': [],
      '/checks/audit': populatedAudit,
      '/checks/onboard': emptyOnboard,
    })
    renderWithProviders(<Checks />)

    expect(await screen.findByText('python')).toBeInTheDocument()
    expect(screen.getByText('new')).toBeInTheDocument()
    expect(screen.getByText('lint')).toBeInTheDocument()
    expect(screen.getByText('ruff check .')).toBeInTheDocument()
    expect(screen.getByText('test')).toBeInTheDocument()
    expect(screen.getByText('pytest -q')).toBeInTheDocument()
    expect(screen.getByText(/chore/)).toBeInTheDocument()
    expect(screen.getByText(/resolves to only the/)).toBeInTheDocument()
  })

  it('phrases smoke-only blueprints honestly for detected-stack and stackless cases', async () => {
    installFetch({
      '/checks/history': [],
      '/checks/audit': smokeOnlyMixedAudit,
      '/checks/onboard': emptyOnboard,
    })
    renderWithProviders(<Checks />)

    // Detected stack: keep the "while <stacks> is detected" wording.
    expect(await screen.findByText(/while Python is detected/i)).toBeInTheDocument()

    // No stack detected: an honest message pointing at the manifest check_sets,
    // never the misleading "while <stack> is detected" phrasing.
    expect(screen.getByText(/no stack was detected/i)).toBeInTheDocument()
    expect(screen.getByText('check_sets')).toBeInTheDocument()
  })

  it('shows a clean empty state when the audit has no proposals', async () => {
    installFetch({
      '/checks/history': [],
      '/checks/audit': emptyAudit,
      '/checks/onboard': emptyOnboard,
    })
    renderWithProviders(<Checks />)

    expect(await screen.findByText(/no upgrades proposed/i)).toBeInTheDocument()
  })
})
