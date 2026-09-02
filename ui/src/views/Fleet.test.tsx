import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Fleet } from './Fleet'
import { installFetch, renderWithProviders } from '../test/utils'
import { uiStore } from '../app/uiStore'
import { execStore } from '../app/execStore'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  execStore.reset()
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

describe('Fleet cancel', () => {
  // Finding 37: cancel lived only in the Console drawer — invisible on the one
  // screen whose job is watching running agents.
  it('offers Cancel inside the card frame, guarded by a confirm naming the run', async () => {
    const mock = installFetch({
      '/fleet': { units: [unit('run-a', [{ ts: 't', event: 'act_started', attempt: 0 }])] },
      '/cancel': { cancelled: true },
    })
    execStore.launch({ id: 'e1', projectId: 'demo', command: 'run' })
    execStore.noteRun('demo', 'run-a')
    renderWithProviders(<Fleet />)

    await userEvent.click(await screen.findByRole('button', { name: 'Cancel run run-a' }))

    // Nothing fires yet — a cancel kills a paid engine turn, so a confirm
    // naming the exact run stands between the tap and the kill.
    expect(mock.calls.some((c) => c.url.includes('/cancel'))).toBe(false)
    expect(screen.getByText(/run-a — the engine stops/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Cancel run' }))

    const call = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/execs/e1/cancel'))
    expect(call).toBeTruthy()
  })

  it('keep-running dismisses the confirm without cancelling', async () => {
    const mock = installFetch({
      '/fleet': { units: [unit('run-a', [{ ts: 't', event: 'act_started', attempt: 0 }])] },
    })
    execStore.launch({ id: 'e1', projectId: 'demo', command: 'run' })
    execStore.noteRun('demo', 'run-a')
    renderWithProviders(<Fleet />)

    await userEvent.click(await screen.findByRole('button', { name: 'Cancel run run-a' }))
    await userEvent.click(screen.getByRole('button', { name: 'Keep running' }))

    expect(mock.calls.some((c) => c.url.includes('/cancel'))).toBe(false)
    expect(screen.queryByText(/engine stops/)).not.toBeInTheDocument()
  })

  it('offers no Cancel when nothing running matches', async () => {
    installFetch({
      '/fleet': { units: [unit('run-a', [{ ts: 't', event: 'act_started', attempt: 0 }])] },
    })
    renderWithProviders(<Fleet />)
    expect(await screen.findByText('tidy the imports')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Cancel run/ })).not.toBeInTheDocument()
  })

  it('never guesses between two running execs without a stem match', async () => {
    installFetch({
      '/fleet': { units: [unit('run-a', [{ ts: 't', event: 'act_started', attempt: 0 }])] },
    })
    execStore.launch({ id: 'e1', projectId: 'demo', command: 'run' })
    execStore.launch({ id: 'e2', projectId: 'demo', command: 'run' })
    renderWithProviders(<Fleet />)
    expect(await screen.findByText('tidy the imports')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Cancel run/ })).not.toBeInTheDocument()
  })
})
