import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ToolWindow } from './ToolWindow'
import { installFetch, renderWithProviders, res } from '../test/utils'
import type { FetchCall } from '../test/utils'
import { uiStore } from '../app/uiStore'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

describe('ToolWindow create/delete', () => {
  it('scaffolds a new blueprint and opens its tab', async () => {
    const mock = installFetch({
      '/blueprints': (call: FetchCall) =>
        call.method === 'POST' ? { raw: 'x', parsed: {} } : [{ name: 'chore', mtime: 1 }],
      '/flows': [],
      '/specialists': [],
      '/loops': [],
      '/primers': [],
      '/prompts': [],
    })
    renderWithProviders(<ToolWindow />)

    await userEvent.click(await screen.findByRole('button', { name: 'New Blueprints' }))
    await userEvent.type(screen.getByPlaceholderText('name'), 'docs')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))

    const post = mock.calls.find((c) => c.method === 'POST')
    expect(post?.body).toEqual({ name: 'docs', raw: '' })
    expect(uiStore.getState().tabs.some((t) => t.title === 'docs.md')).toBe(true)
  })

  it('deletes a blueprint after confirmation', async () => {
    const mock = installFetch({
      '/blueprints': (call: FetchCall) =>
        call.method === 'DELETE' ? res(204, {}) : [{ name: 'chore', mtime: 1 }],
      '/flows': [],
      '/specialists': [],
      '/loops': [],
      '/primers': [],
      '/prompts': [],
    })
    renderWithProviders(<ToolWindow />)

    await userEvent.click(await screen.findByRole('button', { name: 'Delete chore' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    const del = mock.calls.find((c) => c.method === 'DELETE')
    expect(del?.url).toContain('/blueprints/chore')
  })

  it('offers eject for a reserved, non-ejected prompt', async () => {
    installFetch({
      '/blueprints': [],
      '/flows': [],
      '/specialists': [],
      '/loops': [],
      '/primers': [],
      '/prompts': [{ name: 'repair', kind: 'reserved', source: 'default', reserved: true, ejected: false }],
    })
    renderWithProviders(<ToolWindow />)

    expect(await screen.findByRole('button', { name: 'Eject repair' })).toBeInTheDocument()
  })
})
