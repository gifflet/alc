import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ExploreDialog } from './ExploreDialog'
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

const blueprints = [{ name: 'chore', mtime: 1 }]

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  execStore.reset()
})

describe('ExploreDialog', () => {
  it('dispatches an explore exec with the blueprint, task and variants count', async () => {
    const mock = installFetch({
      '/blueprints': blueprints,
      '/engines': engines,
      '/exec': { exec_id: 'x1' },
    })
    renderWithProviders(<ExploreDialog onClose={() => {}} />)

    // The blueprint select auto-picks the only blueprint once it loads.
    await screen.findByDisplayValue('chore')
    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'try two approaches' } })
    fireEvent.change(screen.getByLabelText('Variants'), { target: { value: '3' } })
    await userEvent.click(screen.getByRole('button', { name: 'Explore' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({
      command: 'explore',
      args: { blueprint: 'chore', task: 'try two approaches', variants: 3 },
    })
    expect(execStore.getState().execs[0]?.id).toBe('x1')
  })

  it('forwards a chosen engine and tier', async () => {
    const mock = installFetch({
      '/blueprints': blueprints,
      '/engines': engines,
      '/exec': { exec_id: 'x2' },
    })
    renderWithProviders(<ExploreDialog onClose={() => {}} />)

    await screen.findByDisplayValue('chore')
    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'poke at it' } })
    await screen.findByRole('option', { name: 'mock (default)' })
    fireEvent.change(screen.getByLabelText('Engine'), { target: { value: 'mock' } })
    fireEvent.change(screen.getByLabelText('Tier'), { target: { value: 'deep' } })
    await userEvent.click(screen.getByRole('button', { name: 'Explore' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({
      command: 'explore',
      args: { blueprint: 'chore', task: 'poke at it', variants: 2, engine: 'mock', tier: 'deep' },
    })
  })

  it('closes the dialog on a successful dispatch', async () => {
    installFetch({ '/blueprints': blueprints, '/engines': engines, '/exec': { exec_id: 'x3' } })
    let closed = false
    renderWithProviders(<ExploreDialog onClose={() => (closed = true)} />)

    await screen.findByDisplayValue('chore')
    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'try it' } })
    await userEvent.click(screen.getByRole('button', { name: 'Explore' }))

    expect(closed).toBe(true)
  })

  it('disables Explore until a blueprint and task are set', async () => {
    installFetch({ '/blueprints': [], '/engines': engines, '/exec': { exec_id: 'x4' } })
    renderWithProviders(<ExploreDialog onClose={() => {}} />)

    await screen.findByLabelText('Task')
    expect(screen.getByRole('button', { name: 'Explore' })).toBeDisabled()
  })
})
