import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Compare } from './Compare'
import { installFetch, renderWithProviders } from '../test/utils'
import type { VariantRow } from '../api/types'

const winner: VariantRow = {
  branch: 'alc/variant-1-aaaaaaaa',
  engine: 'mock',
  tier: 'standard',
  success: true,
  checks: 'all passed',
  scorecard: { span: 2, passes: 1, streak: 1, touch: 0 },
  usage: { input_tokens: 100, output_tokens: 50, cost_usd: 1.5 },
  diffstat: { adds: 10, dels: 2, files_deleted: 0 },
}

const loser: VariantRow = {
  branch: 'alc/variant-2-bbbbbbbb',
  engine: 'mock',
  tier: 'standard',
  success: false,
  checks: 'failed: smoke',
  scorecard: { span: 1, passes: 1, streak: 0, touch: 0 },
  usage: null,
  diffstat: null,
}

beforeEach(() => {
  localStorage.clear()
})

describe('Compare', () => {
  it('renders variant rows with branch, checks, scorecard, cost and diffstat', async () => {
    installFetch({ '/variants': [winner, loser] })
    renderWithProviders(<Compare />)

    expect(await screen.findByText('alc/variant-1-aaaaaaaa')).toBeInTheDocument()
    expect(screen.getByText('alc/variant-2-bbbbbbbb')).toBeInTheDocument()
    expect(screen.getByText('all passed')).toBeInTheDocument()
    expect(screen.getByText('failed: smoke')).toBeInTheDocument()
    expect(screen.getByText(/span=2 passes=1 streak=1 touch=0/)).toBeInTheDocument()
    expect(screen.getByText('$1.50')).toBeInTheDocument()
    expect(screen.getByText('+10/-2')).toBeInTheDocument()
  })

  it('shows an empty state when there are no archived variants', async () => {
    installFetch({ '/variants': [] })
    renderWithProviders(<Compare />)

    expect(await screen.findByText(/no archived variants yet/i)).toBeInTheDocument()
  })

  it('adopts a variant only after confirmation', async () => {
    // `/variants/adopt` must be matched before the shorter `/variants` prefix.
    const mock = installFetch({
      '/variants/adopt': { merged: ['alc/variant-1-aaaaaaaa'], conflicted: [], discarded: ['alc/variant-2-bbbbbbbb'] },
      '/variants': [winner, loser],
    })
    renderWithProviders(<Compare />)

    await screen.findByText('alc/variant-1-aaaaaaaa')
    await userEvent.click(screen.getByRole('button', { name: 'Adopt alc/variant-1-aaaaaaaa' }))

    // The mutation must not fire before the confirm dialog is accepted.
    expect(
      mock.calls.some((c) => c.method === 'POST' && c.url.endsWith('/variants/adopt')),
    ).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Adopt' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/variants/adopt'))
    expect(post?.body).toEqual({ branch: 'alc/variant-1-aaaaaaaa' })
  })

  it('surfaces a conflicted winner even though its siblings were still discarded', async () => {
    installFetch({
      '/variants/adopt': { merged: [], conflicted: ['alc/variant-1-aaaaaaaa'], discarded: ['alc/variant-2-bbbbbbbb'] },
      '/variants': [winner],
    })
    renderWithProviders(<Compare />)

    await screen.findByText('alc/variant-1-aaaaaaaa')
    await userEvent.click(screen.getByRole('button', { name: 'Adopt alc/variant-1-aaaaaaaa' }))
    await userEvent.click(screen.getByRole('button', { name: 'Adopt' }))

    const note = await screen.findByText(/left for manual resolution/i)
    expect(note.textContent).toContain('alc/variant-1-aaaaaaaa')
  })
})
