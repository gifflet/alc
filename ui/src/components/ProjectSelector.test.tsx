import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectSelector } from './ProjectSelector'
import { api } from '../api/client'

vi.mock('../ws/WsProvider', () => ({
  useWs: () => ({ status: 'open', client: { on: () => () => {} } }),
}))

const PROJECTS = [
  {
    id: 'p1',
    name: 'alpha',
    path: '/home/dev/alpha',
    available: true,
    default_engine: 'mock',
    queue_pending: 0,
  },
]

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <ProjectSelector activeId="p1" onClose={vi.fn()} onSelect={vi.fn()} />
    </QueryClientProvider>,
  )
}

describe('ProjectSelector removal', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'listProjects').mockResolvedValue(PROJECTS as never)
  })

  it('asks before deregistering, instead of acting on the first click', async () => {
    const remove = vi.spyOn(api, 'removeProject').mockResolvedValue(undefined as never)
    setup()

    fireEvent.click(await screen.findByLabelText('Remove alpha'))

    expect(remove).not.toHaveBeenCalled()
    expect(screen.getByText('Remove project')).toBeInTheDocument()
  })

  it('says the files on disk survive — the question every operator has', async () => {
    setup()
    fireEvent.click(await screen.findByLabelText('Remove alpha'))
    expect(screen.getByText(/files on disk are untouched/)).toBeInTheDocument()
  })

  it('cancelling leaves the project registered', async () => {
    const remove = vi.spyOn(api, 'removeProject').mockResolvedValue(undefined as never)
    setup()
    fireEvent.click(await screen.findByLabelText('Remove alpha'))
    fireEvent.click(screen.getByText('Cancel'))

    await waitFor(() => expect(screen.queryByText('Remove project')).not.toBeInTheDocument())
    expect(remove).not.toHaveBeenCalled()
  })

  it('confirming removes it', async () => {
    const remove = vi.spyOn(api, 'removeProject').mockResolvedValue(undefined as never)
    setup()
    fireEvent.click(await screen.findByLabelText('Remove alpha'))
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(remove).toHaveBeenCalledWith('p1'))
  })
})
