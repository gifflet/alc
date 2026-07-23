import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Conduct } from './Conduct'
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

describe('Conduct', () => {
  it('conducts a goal, forwarding the parallel and enqueue flags', async () => {
    const mock = installFetch({ '/engines': engines, '/exec': { exec_id: 'c1' } })
    renderWithProviders(<Conduct />)

    fireEvent.change(await screen.findByLabelText('Goal'), { target: { value: 'add a settings page' } })
    await userEvent.click(screen.getByLabelText(/Run independent units in parallel/))
    await userEvent.click(screen.getByLabelText(/Enqueue tasks instead/))
    await userEvent.click(screen.getByRole('button', { name: 'Conduct goal' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({
      command: 'conduct',
      args: { goal: 'add a settings page', parallel: true, enqueue: true },
    })
    expect(execStore.getState().execs[0]?.command).toBe('conduct')
  })

  it('adds --strict-stage only when the checkbox is checked', async () => {
    const mock = installFetch({ '/engines': engines, '/exec': { exec_id: 'c2' } })
    renderWithProviders(<Conduct />)

    fireEvent.change(await screen.findByLabelText('Goal'), { target: { value: 'ship the release' } })
    await userEvent.click(screen.getByLabelText(/Enforce the declared stage's mix/))
    await userEvent.click(screen.getByRole('button', { name: 'Conduct goal' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({
      command: 'conduct',
      args: { goal: 'ship the release', 'strict-stage': true },
    })
  })

  it('omits strict-stage when the checkbox is left unchecked', async () => {
    const mock = installFetch({ '/engines': engines, '/exec': { exec_id: 'c3' } })
    renderWithProviders(<Conduct />)

    fireEvent.change(await screen.findByLabelText('Goal'), { target: { value: 'ship the release' } })
    await userEvent.click(screen.getByRole('button', { name: 'Conduct goal' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({ command: 'conduct', args: { goal: 'ship the release' } })
  })
})
