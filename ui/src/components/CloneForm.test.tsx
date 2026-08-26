import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CloneForm } from './CloneForm'
import { api, ApiError } from '../api/client'

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

function setup(onCloned = vi.fn()) {
  handlers.length = 0
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <CloneForm onCloned={onCloned} />
    </QueryClientProvider>,
  )
  const fill = (url = 'https://github.com/o/repo.git', parent = '/home/dev') => {
    fireEvent.change(screen.getByLabelText('Repository URL'), { target: { value: url } })
    fireEvent.change(screen.getByLabelText('Parent directory'), { target: { value: parent } })
  }
  return { onCloned, fill }
}

describe('CloneForm', () => {
  beforeEach(() => {
    vi.spyOn(api, 'cloneRepository').mockResolvedValue({
      exec_id: 'e1',
      destination: '/home/dev/repo',
    })
  })

  it('will not submit without a URL and a destination', () => {
    setup()
    expect(screen.getByRole('button', { name: /Clone/ })).toBeDisabled()
  })

  it('starts the clone and shows git output as it arrives', async () => {
    const { fill } = setup()
    fill()
    fireEvent.click(screen.getByRole('button', { name: /Clone/ }))

    await waitFor(() => expect(screen.getByText('Cloning…')).toBeInTheDocument())
    // The line keeps git's real double space; getByText normalises whitespace,
    // so match on the element's own textContent instead of loosening the line.
    emit({ type: 'exec_output', exec_id: 'e1', line: 'Receiving objects:  47%' })
    // Verbatim git progress answers the question a spinner leaves open.
    await waitFor(() =>
      expect(
        screen.getByText((_, el) => el?.textContent === 'Receiving objects:  47%'),
      ).toBeInTheDocument(),
    )
  })

  it('hands the destination back when git exits clean', async () => {
    const { fill, onCloned } = setup()
    fill()
    fireEvent.click(screen.getByRole('button', { name: /Clone/ }))
    await waitFor(() => expect(screen.getByText('Cloning…')).toBeInTheDocument())

    emit({ type: 'exec_finished', exec_id: 'e1', exit_code: 0 })
    await waitFor(() => expect(onCloned).toHaveBeenCalledWith('/home/dev/repo'))
  })

  it('reports a non-zero exit instead of claiming success', async () => {
    const { fill, onCloned } = setup()
    fill()
    fireEvent.click(screen.getByRole('button', { name: /Clone/ }))
    await waitFor(() => expect(screen.getByText('Cloning…')).toBeInTheDocument())

    emit({ type: 'exec_finished', exec_id: 'e1', exit_code: 128 })
    await waitFor(() => expect(screen.getByText(/exited with code 128/)).toBeInTheDocument())
    expect(onCloned).not.toHaveBeenCalled()
  })

  it('ignores output belonging to another exec', async () => {
    const { fill } = setup()
    fill()
    fireEvent.click(screen.getByRole('button', { name: /Clone/ }))
    await waitFor(() => expect(screen.getByText('Cloning…')).toBeInTheDocument())

    emit({ type: 'exec_output', exec_id: 'someone-else', line: 'not mine' })
    expect(screen.queryByText(/not mine/)).not.toBeInTheDocument()
  })

  it('surfaces the server refusal verbatim', async () => {
    vi.spyOn(api, 'cloneRepository').mockRejectedValue(
      new ApiError("clone URL may not start with '-'", 400, null),
    )
    const { fill } = setup()
    fill('-x')
    fireEvent.click(screen.getByRole('button', { name: /Clone/ }))
    await waitFor(() =>
      expect(screen.getByText(/may not start with '-'/)).toBeInTheDocument(),
    )
  })
})
