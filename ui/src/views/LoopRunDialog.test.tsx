import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoopRunDialog, loopCeiling } from './LoopRunDialog'
import { execStore } from '../app/execStore'
import { uiStore } from '../app/uiStore'
import { installFetch, renderWithProviders } from '../test/utils'

const engines = [
  {
    name: 'mock',
    type: 'mock',
    default: true,
    tiers: { standard: 'mock-small', deep: 'mock-large' },
    healthy: true,
  },
]

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  execStore.reset()
})

describe('LoopRunDialog', () => {
  it('dispatches a loop exec with the name and default interval', async () => {
    const mock = installFetch({ '/engines': engines, '/exec': { exec_id: 'e1' } })
    renderWithProviders(<LoopRunDialog name="deliver" onClose={() => {}} />)

    await userEvent.click(screen.getByRole('button', { name: 'Run' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({ command: 'loop', args: { name: 'deliver', interval: 0 } })
    expect(execStore.getState().execs[0]?.id).toBe('e1')
  })

  it('sends interval, reset and the chosen engine', async () => {
    const mock = installFetch({ '/engines': engines, '/exec': { exec_id: 'e2' } })
    renderWithProviders(<LoopRunDialog name="deliver" onClose={() => {}} />)

    fireEvent.change(screen.getByLabelText('Interval'), { target: { value: '60' } })
    await userEvent.click(screen.getByLabelText("Reset the loop's stopped state first"))
    await screen.findByRole('option', { name: 'mock (default)' })
    fireEvent.change(screen.getByLabelText('Engine'), { target: { value: 'mock' } })
    await userEvent.click(screen.getByRole('button', { name: 'Run' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({
      command: 'loop',
      args: { name: 'deliver', interval: 60, reset: true, engine: 'mock' },
    })
  })

  it('states the ceiling the loop will run to, read from the loop itself', async () => {
    installFetch({
      '/engines': engines,
      '/loops/deliver': { raw: '', parsed: { stop: { max_cycles: 12 } } },
    })
    renderWithProviders(<LoopRunDialog name="deliver" onClose={() => {}} />)

    expect(await screen.findByText('12 cycles')).toBeInTheDocument()
  })

  it('names the budget only when the loop actually sets one', async () => {
    installFetch({
      '/engines': engines,
      '/loops/deliver': { raw: '', parsed: { stop: { max_cycles: 4, budget: { unit: 'usd', max: 5 } } } },
    })
    renderWithProviders(<LoopRunDialog name="deliver" onClose={() => {}} />)

    expect(await screen.findByText('5 usd')).toBeInTheDocument()
  })
})

describe('loopCeiling', () => {
  it('reads max_cycles and the optional budget', () => {
    expect(loopCeiling({ stop: { max_cycles: 3 } })).toEqual({ cycles: 3, budget: null })
    expect(loopCeiling({ stop: { max_cycles: 3, budget: { unit: 'tokens', max: 10 } } })).toEqual({
      cycles: 3,
      budget: '10 tokens',
    })
  })

  it('claims nothing when the loop has not loaded yet', () => {
    // Better silent than a made-up ceiling: undefined is "not read", not "unbounded".
    expect(loopCeiling(undefined)).toEqual({ cycles: null, budget: null })
    expect(loopCeiling({})).toEqual({ cycles: null, budget: null })
  })
})
