import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Checks } from './Checks'
import { installFetch, renderWithProviders } from '../test/utils'
import type { CheckHistoryEntry, ChecksAudit } from '../api/types'

const history: CheckHistoryEntry[] = [
  { name: 'test', runs: 4, passes: 2, pass_rate: 0.5, mean_duration_s: 1.25, flake_score: 1.0 },
]

const emptyAudit: ChecksAudit = { check_sets: [], smoke_only_blueprints: [] }

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

describe('Checks', () => {
  it('renders the history table with pass-rate/duration/flake-score', async () => {
    installFetch({ '/checks/history': history, '/checks/audit': emptyAudit })
    renderWithProviders(<Checks />)

    expect(await screen.findByText('test')).toBeInTheDocument()
    expect(screen.getByText('50% (2/4)')).toBeInTheDocument()
    expect(screen.getByText('1.25s')).toBeInTheDocument()
    expect(screen.getByText('1.00')).toBeInTheDocument()
  })

  it('shows an empty state when there is no run history yet', async () => {
    installFetch({ '/checks/history': [], '/checks/audit': emptyAudit })
    renderWithProviders(<Checks />)

    expect(await screen.findByText(/no check history yet/i)).toBeInTheDocument()
  })

  it('renders proposed check-set upgrades and smoke-only blueprints', async () => {
    installFetch({ '/checks/history': [], '/checks/audit': populatedAudit })
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

  it('shows a clean empty state when the audit has no proposals', async () => {
    installFetch({ '/checks/history': [], '/checks/audit': emptyAudit })
    renderWithProviders(<Checks />)

    expect(await screen.findByText(/no upgrades proposed/i)).toBeInTheDocument()
  })
})
