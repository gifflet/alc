import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Fleet } from './Fleet'
import { installFetch, renderWithProviders } from '../test/utils'
import { uiStore } from '../app/uiStore'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

const STARTED = {
  ts: 't',
  event: 'mandate_started',
  blueprint: 'chore',
  task: 'tidy the imports',
  engine: 'mock',
  model: 'm',
}

function unit(stem: string, extra: Record<string, unknown>[] = []) {
  return { stem, kind: 'run', mtime: 1783828900, truncated: false, events: [STARTED, ...extra] }
}

describe('Fleet', () => {
  it('names the command that would populate it when nothing is running', async () => {
    installFetch({ '/fleet': { units: [] } })
    renderWithProviders(<Fleet />)
    expect(await screen.findByText(/alc tick --concurrency 4/)).toBeInTheDocument()
  })

  it('shows one card per concurrent unit', async () => {
    installFetch({
      '/fleet': {
        units: [
          unit('run-a', [{ ts: 't', event: 'act_started', attempt: 0 }]),
          unit('run-b', [{ ts: 't', event: 'verify_started', attempt: 0, checks: ['build'] }]),
        ],
      },
    })
    renderWithProviders(<Fleet />)
    expect(await screen.findByText(/Act · attempt 1/)).toBeInTheDocument()
    expect(screen.getByText(/Verify · attempt 1/)).toBeInTheDocument()
    expect(screen.getAllByRole('button')).toHaveLength(2)
  })

  it('opens the run detail tab when a card is activated', async () => {
    installFetch({ '/fleet': { units: [unit('run-a', [{ ts: 't', event: 'act_started', attempt: 0 }])] } })
    renderWithProviders(<Fleet />)
    await userEvent.click(await screen.findByRole('button'))
    expect(uiStore.getState().activeTabId).toBe('run:run-a')
  })
})
