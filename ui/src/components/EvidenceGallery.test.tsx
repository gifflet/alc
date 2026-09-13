import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EvidenceGallery } from './EvidenceGallery'
import { api } from '../api/client'

// jsdom has no object-URL machinery.
beforeEach(() => {
  vi.restoreAllMocks()
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock')
  globalThis.URL.revokeObjectURL = vi.fn()
})

describe('EvidenceGallery', () => {
  it('renders a backend JSON response pretty-printed in a text panel', async () => {
    vi.spyOn(api, 'artifactText').mockResolvedValue('{"status":"ok","tvs":3}')
    render(
      <EvidenceGallery
        id="p1"
        artifacts={[{ path: '.alc/artifacts/r/response.json', type: 'data' }]}
      />
    )
    // Filename in the header, type chip, and the pretty-printed JSON body.
    expect(await screen.findByText('response.json')).toBeInTheDocument()
    // Pretty-print puts each key on its own line with two-space indent.
    const pre = await screen.findByText(/"status": "ok"/)
    expect(pre.textContent).toContain('"tvs": 3')
  })

  it('shows an HTML response as source text, not rendered', async () => {
    vi.spyOn(api, 'artifactText').mockResolvedValue('<!doctype html><title>Hub</title>')
    render(
      <EvidenceGallery id="p1" artifacts={[{ path: 'a/health-check.txt', type: 'log' }]} />
    )
    expect(await screen.findByText(/<!doctype html>/)).toBeInTheDocument()
  })

  it('truncates a very large preview and says so', async () => {
    vi.spyOn(api, 'artifactText').mockResolvedValue('x'.repeat(120_000))
    render(<EvidenceGallery id="p1" artifacts={[{ path: 'a/big.txt', type: 'log' }]} />)
    expect(await screen.findByText(/Preview truncated at/)).toBeInTheDocument()
  })

  it('surfaces a load error instead of a blank panel', async () => {
    vi.spyOn(api, 'artifactText').mockRejectedValue(new Error('401 Unauthorized'))
    render(<EvidenceGallery id="p1" artifacts={[{ path: 'a/x.txt', type: 'log' }]} />)
    expect(await screen.findByText(/Could not load: 401 Unauthorized/)).toBeInTheDocument()
  })

  it('renders an image as a carousel and steps between screenshots', async () => {
    const url = vi.spyOn(api, 'artifactObjectUrl').mockResolvedValue('blob:img')
    render(
      <EvidenceGallery
        id="p1"
        artifacts={[
          { path: 'a/home.png', type: 'image' },
          { path: 'a/detail.png', type: 'image' },
        ]}
      />
    )
    // Counter shows two images; first is fetched.
    expect(await screen.findByText('1/2')).toBeInTheDocument()
    await waitFor(() => expect(url).toHaveBeenCalledWith('p1', 'a/home.png'))
    await userEvent.click(screen.getByRole('button', { name: /next screenshot/i }))
    expect(await screen.findByText('2/2')).toBeInTheDocument()
    await waitFor(() => expect(url).toHaveBeenCalledWith('p1', 'a/detail.png'))
  })

  it('separates images (carousel) from documents (text) in a mixed set', async () => {
    vi.spyOn(api, 'artifactObjectUrl').mockResolvedValue('blob:img')
    vi.spyOn(api, 'artifactText').mockResolvedValue('poll ok')
    render(
      <EvidenceGallery
        id="p1"
        artifacts={[
          { path: 'a/shot.png', type: 'image' },
          { path: 'a/health-poll.log', type: 'log' },
        ]}
      />
    )
    // No multi-image counter for a single image; the log renders as text.
    expect(await screen.findByText('health-poll.log')).toBeInTheDocument()
    expect(await screen.findByText('poll ok')).toBeInTheDocument()
    expect(screen.queryByText('1/1')).not.toBeInTheDocument()
  })

  it('warns that no screen was verified on a service run with no image', async () => {
    vi.spyOn(api, 'artifactText').mockResolvedValue('poll ok')
    render(
      <EvidenceGallery
        id="p1"
        artifacts={[{ path: 'a/health-poll.log', type: 'log' }]}
        serviceRun
      />
    )
    expect(await screen.findByText(/did not visually verify a screen/i)).toBeInTheDocument()
    // And it says how to fix it.
    expect(screen.getByText(/playwright screenshot/i)).toBeInTheDocument()
  })

  it('does not warn when the service run captured a screenshot', async () => {
    vi.spyOn(api, 'artifactObjectUrl').mockResolvedValue('blob:img')
    render(
      <EvidenceGallery id="p1" artifacts={[{ path: 'a/home.png', type: 'image' }]} serviceRun />
    )
    await screen.findByText('home.png')
    expect(screen.queryByText(/did not visually verify/i)).not.toBeInTheDocument()
  })

  it('does not warn on a non-service run without images', async () => {
    vi.spyOn(api, 'artifactText').mockResolvedValue('data')
    render(<EvidenceGallery id="p1" artifacts={[{ path: 'a/x.json', type: 'data' }]} />)
    await screen.findByText('x.json')
    expect(screen.queryByText(/did not visually verify/i)).not.toBeInTheDocument()
  })
})
