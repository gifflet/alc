import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BottomTabBar, DESTINATIONS } from './BottomTabBar'

describe('BottomTabBar', () => {
  it('keeps exactly five destinations — a phone cannot hold more', () => {
    expect(DESTINATIONS).toHaveLength(5)
    // Dashboard leads (it is the project root); Runs moved to More.
    expect(DESTINATIONS.map((d) => d.view)).toEqual(['dashboard', 'inbox', 'fleet', 'queue', 'more'])
  })

  it('marks the active destination for assistive technology, not just by colour', () => {
    render(<BottomTabBar active="queue" onSelect={() => {}} />)
    expect(screen.getByLabelText('Queue')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByLabelText('Fleet')).not.toHaveAttribute('aria-current')
  })

  it('carries the inbox count in the accessible name', () => {
    render(<BottomTabBar active={null} onSelect={() => {}} inboxCount={2} />)
    expect(screen.getByLabelText('Inbox, 2 waiting')).toBeInTheDocument()
  })

  it('hides the badge at zero', () => {
    render(<BottomTabBar active={null} onSelect={() => {}} inboxCount={0} />)
    expect(screen.getByLabelText('Inbox')).toBeInTheDocument()
  })

  it('reports the chosen destination', async () => {
    const onSelect = vi.fn()
    render(<BottomTabBar active={null} onSelect={onSelect} />)
    await userEvent.click(screen.getByLabelText('More'))
    expect(onSelect).toHaveBeenCalledWith('more')
  })

  it('reserves the safe area so the gesture bar cannot cover the targets', () => {
    const { container } = render(<BottomTabBar active={null} onSelect={() => {}} />)
    const nav = container.querySelector('nav')!
    expect(nav.className).toContain('safe-area-inset-bottom')
  })
})
