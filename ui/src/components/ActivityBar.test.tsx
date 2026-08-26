import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ActivityBar } from './ActivityBar'
import { uiStore } from '../app/uiStore'

beforeEach(() => {
  uiStore.reset()
})

describe('ActivityBar', () => {
  it('calls onOpenSpike when the Spike rail button is clicked', async () => {
    let opened = false
    render(<ActivityBar onOpenProjects={() => {}} onOpenSpike={() => (opened = true)} />)

    await userEvent.click(screen.getByLabelText('Spike'))

    expect(opened).toBe(true)
  })
})

describe('ActivityBar inbox badge', () => {
  it('shows the pending-decision count', () => {
    render(<ActivityBar onOpenProjects={() => {}} onOpenSpike={() => {}} inboxCount={3} />)
    expect(screen.getByText('3')).toBeInTheDocument()
    // The count is in the accessible name too, so it is not colour/shape-only.
    expect(screen.getByLabelText('Inbox, 3 waiting')).toBeInTheDocument()
  })

  it('hides the badge at zero rather than showing a 0', () => {
    render(<ActivityBar onOpenProjects={() => {}} onOpenSpike={() => {}} inboxCount={0} />)
    expect(screen.queryByText('0')).toBeNull()
    expect(screen.getByLabelText('Inbox')).toBeInTheDocument()
  })

  it('renders without a project context (it is presentational)', () => {
    // Regression guard: fetching inside the rail once made this throw.
    expect(() =>
      render(<ActivityBar onOpenProjects={() => {}} onOpenSpike={() => {}} />),
    ).not.toThrow()
  })
})
