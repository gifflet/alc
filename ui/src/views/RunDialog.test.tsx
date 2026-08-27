import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RunDialog } from './RunDialog'
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

describe('RunDialog', () => {
  it('dispatches a run exec with the blueprint, task and isolate flag', async () => {
    const mock = installFetch({ '/engines': engines, '/exec': { exec_id: 'e1' } })
    renderWithProviders(<RunDialog command="run" name="chore" onClose={() => {}} />)

    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'fix the bug' } })
    await userEvent.click(screen.getByRole('button', { name: /Options/ }))
    await userEvent.click(
      screen.getByLabelText('Work on a separate branch, leaving my files untouched'),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Run' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({
      command: 'run',
      args: { blueprint: 'chore', task: 'fix the bug', isolate: true },
    })
    expect(execStore.getState().execs[0]?.id).toBe('e1')
  })

  it('sends the flow name under the flow key with a chosen engine and tier', async () => {
    const mock = installFetch({ '/engines': engines, '/exec': { exec_id: 'e2' } })
    renderWithProviders(<RunDialog command="flow" name="ship" onClose={() => {}} />)

    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'ship it' } })
    await userEvent.click(screen.getByRole('button', { name: /Options/ }))
    await screen.findByRole('option', { name: 'mock (default)' })
    fireEvent.change(screen.getByLabelText('Engine'), { target: { value: 'mock' } })
    fireEvent.change(screen.getByLabelText('Tier'), { target: { value: 'deep' } })
    await userEvent.click(screen.getByRole('button', { name: 'Run' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({
      command: 'flow',
      args: { flow: 'ship', task: 'ship it', engine: 'mock', tier: 'deep' },
    })
  })

  it('omits tier and isolate for a specialist', async () => {
    const mock = installFetch({ '/engines': engines, '/exec': { exec_id: 'e3' } })
    renderWithProviders(<RunDialog command="specialist" name="db" onClose={() => {}} />)

    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'index the table' } })
    expect(screen.queryByLabelText('Tier')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Run' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({ command: 'specialist', args: { name: 'db', task: 'index the table' } })
  })
})
