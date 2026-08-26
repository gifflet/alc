import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Runs } from './Runs'
import { installFetch, renderWithProviders } from '../test/utils'
import { uiStore } from '../app/uiStore'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

describe('Runs', () => {
  it('lists runs and marks a live one', async () => {
    installFetch({
      '/runs': {
        runs: [
          { stem: 'finished-run', kind: 'run', title: 'tidy the imports', unit: 'chore', mtime: 1783828795, size: 712, finished: true },
          { stem: 'live-run', kind: 'flow', title: 'ship the changelog', unit: 'ship', mtime: 1783828900, size: 200, finished: false },
        ],
        total: 2,
      },
    })
    renderWithProviders(<Runs />)
    expect(await screen.findByText('tidy the imports')).toBeInTheDocument()
    expect(screen.getByText('live')).toBeInTheDocument()
  })

  it('marks an interrupted run as stale, not live', async () => {
    installFetch({
      '/runs': {
        runs: [
          {
            stem: 'stale-run',
            kind: 'flow',
            mtime: 1783820000,
            size: 300,
            finished: false,
            stale: true,
          },
        ],
        total: 1,
      },
    })
    renderWithProviders(<Runs />)
    expect(await screen.findByText('stale')).toBeInTheDocument()
    expect(screen.queryByText('live')).not.toBeInTheDocument()
  })

  it('opens a run tab when a row is clicked', async () => {
    installFetch({
      '/runs': {
        runs: [{ stem: 'finished-run', kind: 'run', title: 'tidy the imports', unit: 'chore', mtime: 1783828795, size: 712, finished: true }],
        total: 1,
      },
    })
    renderWithProviders(<Runs />)
    await userEvent.click(await screen.findByText('tidy the imports'))
    const tabs = uiStore.getState().tabs
    expect(tabs.map((t) => t.id)).toContain('run:finished-run')
  })

  it('renders an empty state naming the concrete first action', async () => {
    installFetch({ '/runs': { runs: [], total: 0 } })
    renderWithProviders(<Runs />)
    // Mirrors `alc init`'s golden-path "Next:" — name the action, not just the
    // fact, and in the exact syntax `alc run` accepts (the task is positional).
    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument()
    expect(screen.getByText(/alc run chore "<task>"/)).toBeInTheDocument()
  })
})

describe('Runs naming', () => {
  it('leads with what the run was asked to do, not the stem', async () => {
    installFetch({
      '/runs': {
        runs: [
          {
            stem: '20260825T110000-run-chore-tidy-aa1',
            kind: 'run',
            title: 'tidy the imports in the auth module',
            unit: 'chore',
            mtime: 1783828795,
            size: 712,
            finished: true,
          },
        ],
        total: 1,
      },
    })
    renderWithProviders(<Runs />)
    expect(await screen.findByText('tidy the imports in the auth module')).toBeInTheDocument()
    // The stem stays visible — it is what you paste into `alc runs show` —
    // now sharing its line with the unit that ran it.
    expect(screen.getByText(/chore · 20260825T110000-run-chore-tidy-aa1/)).toBeInTheDocument()
  })

  it('falls back to the stem when the log has no header yet', async () => {
    installFetch({
      '/runs': {
        runs: [
          { stem: 'headless-run', kind: 'run', title: '', unit: '', mtime: 1783828795, size: 10, finished: false },
        ],
        total: 1,
      },
    })
    renderWithProviders(<Runs />)
    // One name, not an empty cell above the stem.
    expect(await screen.findByText('headless-run')).toBeInTheDocument()
  })

  it('carries the unit on the identifier line, not as its own column', async () => {
    installFetch({
      '/runs': {
        runs: [
          { stem: 's', kind: 'flow', title: 'add a changelog entry', unit: 'ship', mtime: 1783828795, size: 10, finished: true },
        ],
        total: 1,
      },
    })
    renderWithProviders(<Runs />)
    // Folded in with the stem: it costs no column width and reads as provenance.
    expect(await screen.findByText(/ship · s/)).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Unit' })).toBeNull()
  })
})

describe('Runs columns', () => {
  const RUN = {
    stem: '20260825T110000-run-chore-tidy-aa1',
    kind: 'run',
    title: 'tidy the imports',
    unit: 'chore',
    mtime: 1783828795,
    size: 712,
    finished: true,
  }

  it('carries the state as a word beside the dot, not colour alone', async () => {
    installFetch({ '/runs': { runs: [RUN], total: 1 } })
    renderWithProviders(<Runs />)
    expect(await screen.findByText('finished')).toBeInTheDocument()
    // One State column, not a bare dot plus a duplicate text column.
    expect(screen.getAllByRole('columnheader', { name: 'State' })).toHaveLength(1)
  })

  it('does not spend a column on the log file size', async () => {
    installFetch({ '/runs': { runs: [RUN], total: 1 } })
    renderWithProviders(<Runs />)
    await screen.findByText('tidy the imports')
    // It is the size of the LOG, not of the work — diagnostic, not operational.
    expect(screen.queryByRole('columnheader', { name: 'Size' })).toBeNull()
    expect(screen.queryByText('712 B')).toBeNull()
  })

  it('keeps the columns an operator scans: kind, run, state, when', async () => {
    installFetch({ '/runs': { runs: [RUN], total: 1 } })
    renderWithProviders(<Runs />)
    await screen.findByText('tidy the imports')
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent?.trim())
    expect(headers).toEqual(['State', 'Kind', 'Run', 'When'])
  })
})
