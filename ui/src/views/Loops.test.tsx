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
  it('blocks the run controls and explains why when the working tree is dirty', async () => {
    installFetch(routes({ dirty: true }))
    renderWithProviders(<Loops />)

    // The concise inline note names the block AND what unblocks it.
    expect(await screen.findByText(/Working tree not clean/i)).toBeInTheDocument()
    expect(screen.getByText(/commit or stash your changes/i)).toBeInTheDocument()

    // Both autonomous-run controls are disabled while the tree is dirty.
    expect(screen.getByLabelText('Run cycle deliver')).toBeDisabled()
    expect(screen.getByLabelText('Run loop deliver')).toBeDisabled()
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
