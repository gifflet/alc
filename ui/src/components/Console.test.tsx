import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Console } from './Console'
import { execStore } from '../app/execStore'
import { uiStore } from '../app/uiStore'
import { installFetch, renderWithProviders } from '../test/utils'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  execStore.reset()
})

describe('Console', () => {
  it('shows the selected exec output and only this project\'s execs', () => {
    execStore.launch({ id: 'e1', projectId: 'demo', command: 'run' })
    execStore.output({ execId: 'e1', projectId: 'demo', line: 'building…' })
    execStore.launch({ id: 'e2', projectId: 'other', command: 'flow' })
    installFetch({})
    renderWithProviders(<Console />)

    expect(screen.getByText('building…')).toBeInTheDocument()
    expect(screen.getAllByText('run').length).toBeGreaterThan(0)
    expect(screen.queryByText('flow')).not.toBeInTheDocument()
  })

  it('cancels a running exec', async () => {
    execStore.launch({ id: 'e1', projectId: 'demo', command: 'run' })
    const mock = installFetch({ '/cancel': { cancelled: true } })
    renderWithProviders(<Console />)

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    const call = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/execs/e1/cancel'))
    expect(call).toBeTruthy()
  })

  it('opens a run tab from a view-run link', async () => {
    execStore.launch({ id: 'e1', projectId: 'demo', command: 'run' })
    execStore.noteRun('demo', 'run-abc')
    installFetch({})
    renderWithProviders(<Console />)

    await userEvent.click(screen.getByRole('button', { name: /view run/ }))
    expect(uiStore.getState().tabs.some((t) => t.id === 'run:run-abc')).toBe(true)
  })

  it('removes an exec, clearing the pane', async () => {
    execStore.launch({ id: 'e1', projectId: 'demo', command: 'run' })
    execStore.output({ execId: 'e1', projectId: 'demo', line: 'line one' })
    installFetch({})
    renderWithProviders(<Console />)

    await userEvent.click(screen.getByRole('button', { name: 'Close exec' }))
    expect(execStore.getState().execs).toHaveLength(0)
    expect(screen.getByText(/No executions yet/)).toBeInTheDocument()
  })
})
