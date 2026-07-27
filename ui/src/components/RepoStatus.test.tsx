import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { RepoStatus } from './RepoStatus'
import { installFetch, renderWithProviders } from '../test/utils'
import type { WorktreeStatus } from '../api/types'

// A full RepoStatus with sane defaults; each test overrides only what it means to.
function wt(overrides: Partial<WorktreeStatus> = {}): WorktreeStatus {
  return {
    available: true,
    dirty: false,
    branch: 'main',
    detached: false,
    upstream: 'origin/main',
    ahead: 0,
    behind: 0,
    untracked: 0,
    ...overrides,
  }
}

describe('RepoStatus', () => {
  it('renders the branch, an ahead chip and a dirty warn dot', async () => {
    installFetch({ '/worktree': wt({ dirty: true, ahead: 1, behind: 0, untracked: 2 }) })
    renderWithProviders(<RepoStatus />)

    expect(await screen.findByText('main')).toBeInTheDocument()
    // Only the non-zero half renders: ahead=1 -> "↑1" (no ↓0).
    expect(screen.getByText('↑1')).toBeInTheDocument()
    // The dirty warn dot carries the untracked count in its own title.
    expect(screen.getByTitle(/uncommitted changes .* 2 untracked/i)).toBeInTheDocument()
  })

  it('renders nothing when the project is off git (available=false)', async () => {
    installFetch({ '/worktree': wt({ available: false }) })
    const { container } = renderWithProviders(<RepoStatus />)

    // Let the query settle; the component still renders nothing off-git.
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(container).toBeEmptyDOMElement()
  })

  it('shows no ahead/behind chip when there is no upstream', async () => {
    installFetch({ '/worktree': wt({ upstream: null, ahead: null, behind: null }) })
    renderWithProviders(<RepoStatus />)

    expect(await screen.findByText('main')).toBeInTheDocument()
    expect(screen.queryByText(/↑|↓/)).not.toBeInTheDocument()
  })

  it('carries the no-auto-fetch honesty tooltip', async () => {
    installFetch({ '/worktree': wt({ ahead: 2, behind: 1 }) })
    renderWithProviders(<RepoStatus />)

    // The tooltip is required by the no-auto-fetch constraint.
    expect(await screen.findByTitle(/last fetch/i)).toBeInTheDocument()
  })
})
