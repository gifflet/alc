import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SpikeDialog } from './SpikeDialog'
import { execStore } from '../app/execStore'
import { uiStore } from '../app/uiStore'
import { installFetch, renderWithProviders } from '../test/utils'

const engines = [
  { name: 'mock', type: 'mock', default: true, tiers: { standard: 'mock-small' }, healthy: true },
]

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  execStore.reset()
})

describe('SpikeDialog', () => {
  it('dispatches a spike exec with just the task', async () => {
    const mock = installFetch({ '/engines': engines, '/exec': { exec_id: 's1' } })
    renderWithProviders(<SpikeDialog onClose={() => {}} />)

    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'try a prototype' } })
    await userEvent.click(screen.getByRole('button', { name: 'Run' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({ command: 'spike', args: { task: 'try a prototype' } })
    expect(execStore.getState().execs[0]?.id).toBe('s1')
  })

  it('forwards a chosen engine', async () => {
    const mock = installFetch({ '/engines': engines, '/exec': { exec_id: 's2' } })
    renderWithProviders(<SpikeDialog onClose={() => {}} />)

    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'poke at the API' } })
    await screen.findByRole('option', { name: 'mock (default)' })
    fireEvent.change(screen.getByLabelText('Engine'), { target: { value: 'mock' } })
    await userEvent.click(screen.getByRole('button', { name: 'Run' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({
      command: 'spike',
      args: { task: 'poke at the API', engine: 'mock' },
    })
  })

  it('closes the dialog on a successful dispatch', async () => {
    installFetch({ '/engines': engines, '/exec': { exec_id: 's3' } })
    let closed = false
    renderWithProviders(<SpikeDialog onClose={() => (closed = true)} />)

    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'try a prototype' } })
    await userEvent.click(screen.getByRole('button', { name: 'Run' }))

    expect(closed).toBe(true)
  })

  it('disables Run until a task is entered', async () => {
    installFetch({ '/engines': engines, '/exec': { exec_id: 's4' } })
    renderWithProviders(<SpikeDialog onClose={() => {}} />)

    await screen.findByLabelText('Task')
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled()
  })
})
