import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Loops } from './Loops'
import { uiStore } from '../app/uiStore'
import { installFetch, renderWithProviders } from '../test/utils'
import type { LoopState, WorktreeStatus } from '../api/types'

const loopsList = [{ name: 'deliver', mtime: 0 }]

const loopState: LoopState = {
  name: 'deliver',
  status: 'pending',
  cycle: 0,
  consecutive_no_progress: 0,
  budget_used: {},
  stopped_reason: null,
}

// Route order matters: installFetch matches by substring, first match wins, so
// the specific `/loops/deliver/state` must precede the `/loops` collection list.
function routes(worktree: WorktreeStatus) {
  return {
    '/loops/deliver/state': loopState,
    '/worktree': worktree,
    '/loops': loopsList,
  }
}

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

describe('Loops', () => {
  it('warns but keeps the run controls enabled when the tree is dirty', async () => {
    installFetch(routes({ dirty: true }))
    renderWithProviders(<Loops />)

    // The banner sets expectations — it no longer gates the run.
    expect(await screen.findByText(/Working tree not clean/i)).toBeInTheDocument()

    // A dirty tree is safe: the run proceeds, so both controls stay live.
    expect(screen.getByLabelText('Run cycle deliver')).not.toBeDisabled()
    expect(screen.getByLabelText('Run loop deliver')).not.toBeDisabled()
  })

  it('renders normally with the run controls enabled when the tree is clean', async () => {
    installFetch(routes({ dirty: false }))
    renderWithProviders(<Loops />)

    // The row renders and both run controls are live — no block note in sight.
    expect(await screen.findByLabelText('Run cycle deliver')).not.toBeDisabled()
    expect(screen.getByLabelText('Run loop deliver')).not.toBeDisabled()
    expect(screen.queryByText(/Working tree not clean/i)).not.toBeInTheDocument()
  })
})
