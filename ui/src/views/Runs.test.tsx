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
          { stem: 'finished-run', kind: 'run', mtime: 1783828795, size: 712, finished: true },
          { stem: 'live-run', kind: 'flow', mtime: 1783828900, size: 200, finished: false },
        ],
        total: 2,
      },
    })
    renderWithProviders(<Runs />)
    expect(await screen.findByText('finished-run')).toBeInTheDocument()
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
        runs: [{ stem: 'finished-run', kind: 'run', mtime: 1783828795, size: 712, finished: true }],
        total: 1,
      },
    })
    renderWithProviders(<Runs />)
    await userEvent.click(await screen.findByText('finished-run'))
    const tabs = uiStore.getState().tabs
    expect(tabs.map((t) => t.id)).toContain('run:finished-run')
  })

  it('renders an empty state when there are no runs', async () => {
    installFetch({ '/runs': { runs: [], total: 0 } })
    renderWithProviders(<Runs />)
    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument()
  })
})
