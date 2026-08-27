import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DirectoryBrowser } from './DirectoryBrowser'
import { api } from '../api/client'
import type { DirectoryListing } from '../api/types'

const listing = (over: Partial<DirectoryListing> = {}): DirectoryListing => ({
  path: '/home/dev',
  parent: '/home',
  is_alc_project: false,
  is_git_repo: false,
  entries: [
    { name: 'work', path: '/home/dev/work', is_alc_project: false, is_git_repo: false },
    { name: 'alc-app', path: '/home/dev/alc-app', is_alc_project: true, is_git_repo: true },
  ],
  ...over,
})

function setup(onPick = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <DirectoryBrowser onPick={onPick} />
    </QueryClientProvider>,
  )
  return { onPick }
}

describe('DirectoryBrowser', () => {
  beforeEach(() => {
    vi.spyOn(api, 'browseDirectory').mockResolvedValue(listing())
  })

  it('opens at the server home, without the caller naming a path', async () => {
    setup()
    await waitFor(() => expect(screen.getByText('work')).toBeInTheDocument())
    expect(api.browseDirectory).toHaveBeenCalledWith(undefined, false)
  })

  it('marks directories that are already ALC projects', async () => {
    setup()
    await waitFor(() => expect(screen.getByText('alc project')).toBeInTheDocument())
  })

  it('descends when the row is clicked', async () => {
    setup()
    await waitFor(() => expect(screen.getByText('work')).toBeInTheDocument())
    fireEvent.click(screen.getByText('work'))
    await waitFor(() =>
      expect(api.browseDirectory).toHaveBeenCalledWith('/home/dev/work', false),
    )
  })

  it('picks with the check, without descending', async () => {
    const { onPick } = setup()
    await waitFor(() => expect(screen.getByText('work')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Use work'))
    expect(onPick).toHaveBeenCalledWith('/home/dev/work')
    // Selecting must not also navigate, or a folder you meant to open registers
    // itself instead.
    expect(api.browseDirectory).toHaveBeenCalledTimes(1)
  })

  it('picks the directory it is currently showing', async () => {
    const { onPick } = setup()
    await waitFor(() => expect(screen.getByText('Use this directory')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Use this directory'))
    expect(onPick).toHaveBeenCalledWith('/home/dev')
  })

  it('disables the step-up control at the filesystem root', async () => {
    vi.spyOn(api, 'browseDirectory').mockResolvedValue(listing({ path: '/', parent: null }))
    setup()
    await waitFor(() =>
      expect(screen.getByLabelText('Parent directory')).toBeDisabled(),
    )
  })

  it('asks for hidden directories only when the box is ticked', async () => {
    setup()
    await waitFor(() => expect(screen.getByText('work')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText(/Hidden/i, { selector: 'input' }))
    await waitFor(() => expect(api.browseDirectory).toHaveBeenCalledWith(undefined, true))
  })

  it('offers to set ALC up when the directory is not a project yet', async () => {
    const onAdopt = vi.fn()
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <DirectoryBrowser onPick={vi.fn()} onAdopt={onAdopt} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByText('Set up ALC here')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Set up ALC here'))
    expect(onAdopt).toHaveBeenCalledWith('/home/dev')
  })

  it('does not offer setup for a directory that is already a project', async () => {
    vi.spyOn(api, 'browseDirectory').mockResolvedValue(listing({ is_alc_project: true }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <DirectoryBrowser onPick={vi.fn()} onAdopt={vi.fn()} />
      </QueryClientProvider>,
    )
    await waitFor(() =>
      expect(screen.getByText(/Ready to register/)).toBeInTheDocument(),
    )
    expect(screen.queryByText('Set up ALC here')).not.toBeInTheDocument()
  })

  it('shows the reason when a directory cannot be read', async () => {
    vi.spyOn(api, 'browseDirectory').mockRejectedValue(new Error('permission denied reading /root'))
    setup()
    await waitFor(() =>
      expect(screen.getByText(/permission denied reading/)).toBeInTheDocument(),
    )
  })
})
