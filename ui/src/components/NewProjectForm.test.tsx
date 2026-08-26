import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NewProjectForm } from './NewProjectForm'
import { ApiError, api } from '../api/client'

const handlers: ((msg: unknown) => void)[] = []

vi.mock('../ws/WsProvider', () => ({
  useWs: () => ({
    status: 'open',
    client: {
      on: (fn: (msg: unknown) => void) => {
        handlers.push(fn)
        return () => handlers.splice(handlers.indexOf(fn), 1)
      },
    },
  }),
}))

const emit = (msg: unknown) => handlers.forEach((h) => h(msg))

function setup(onCreated = vi.fn()) {
  handlers.length = 0
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <NewProjectForm onCreated={onCreated} />
    </QueryClientProvider>,
  )
  const fill = () => {
    fireEvent.change(screen.getByLabelText('Parent directory for the new project'), {
      target: { value: '/home/dev' },
    })
    fireEvent.change(screen.getByLabelText('New project name'), { target: { value: 'fresh' } })
  }
  return { onCreated, fill }
}

describe('NewProjectForm', () => {
  beforeEach(() => {
    vi.spyOn(api, 'newProject').mockResolvedValue({
      exec_id: 'e9',
      destination: '/home/dev/fresh',
    })
  })

  it('needs both a parent and a name', () => {
    setup()
    expect(screen.getByRole('button', { name: /Create/ })).toBeDisabled()
  })

  it('asks for a git repository by default', async () => {
    const { fill } = setup()
    fill()
    fireEvent.click(screen.getByRole('button', { name: /Create/ }))
    // Isolation, landing and the commit step all need one, so the default
    // must not be silently off.
    await waitFor(() => expect(api.newProject).toHaveBeenCalledWith('/home/dev', 'fresh', true))
  })

  it('honours unticking the git box', async () => {
    const { fill } = setup()
    fill()
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /Create/ }))
    await waitFor(() => expect(api.newProject).toHaveBeenCalledWith('/home/dev', 'fresh', false))
  })

  it('shows what alc init reports while it runs', async () => {
    const { fill } = setup()
    fill()
    fireEvent.click(screen.getByRole('button', { name: /Create/ }))
    await waitFor(() => expect(screen.getByText('Creating…')).toBeInTheDocument())

    emit({ type: 'exec_output', exec_id: 'e9', line: 'Detected Python — scaffolded real checks' })
    await waitFor(() =>
      expect(screen.getByText(/Detected Python/)).toBeInTheDocument(),
    )
  })

  it('hands the path back only when init succeeds', async () => {
    const { fill, onCreated } = setup()
    fill()
    fireEvent.click(screen.getByRole('button', { name: /Create/ }))
    await waitFor(() => expect(screen.getByText('Creating…')).toBeInTheDocument())

    emit({ type: 'exec_finished', exec_id: 'e9', exit_code: 0 })
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('/home/dev/fresh'))
  })

  it('reports a failed init instead of registering a broken project', async () => {
    const { fill, onCreated } = setup()
    fill()
    fireEvent.click(screen.getByRole('button', { name: /Create/ }))
    await waitFor(() => expect(screen.getByText('Creating…')).toBeInTheDocument())

    emit({ type: 'exec_finished', exec_id: 'e9', exit_code: 1 })
    await waitFor(() => expect(screen.getByText(/exited with code 1/)).toBeInTheDocument())
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('surfaces the server refusal verbatim', async () => {
    vi.spyOn(api, 'newProject').mockRejectedValue(
      new ApiError("'/home/dev/fresh' already exists and is not empty", 400, null),
    )
    const { fill } = setup()
    fill()
    fireEvent.click(screen.getByRole('button', { name: /Create/ }))
    await waitFor(() =>
      expect(screen.getByText(/already exists and is not empty/)).toBeInTheDocument(),
    )
  })
})
