import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CommandPalette } from './CommandPalette'
import type { Command } from '../lib/commandIndex'

function commands(run = vi.fn()): Command[] {
  return [
    { id: 'view:fleet', kind: 'view', label: 'Fleet', run },
    { id: 'view:queue', kind: 'view', label: 'Queue', run },
    { id: 'blueprints:chore', kind: 'blueprint', label: 'chore', hint: 'chore.md', run },
    { id: 'run:abc', kind: 'run', label: '20260825-run-chore-abc', hint: 'run', run },
  ]
}

describe('CommandPalette', () => {
  it('is a labelled dialog with the search focused', () => {
    render(<CommandPalette commands={commands()} onClose={() => {}} />)
    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
    expect(screen.getByLabelText('Search commands')).toHaveFocus()
  })

  it('groups results by kind', () => {
    render(<CommandPalette commands={commands()} onClose={() => {}} />)
    expect(screen.getByText('Views')).toBeInTheDocument()
    expect(screen.getByText('Blueprints')).toBeInTheDocument()
    expect(screen.getByText('Runs')).toBeInTheDocument()
  })

  it('filters as the operator types', async () => {
    render(<CommandPalette commands={commands()} onClose={() => {}} />)
    await userEvent.type(screen.getByLabelText('Search commands'), 'chore')
    expect(screen.getByText('chore')).toBeInTheDocument()
    expect(screen.queryByText('Fleet')).toBeNull()
  })

  it('activates the selection with Enter and closes', async () => {
    const run = vi.fn()
    const onClose = vi.fn()
    render(<CommandPalette commands={commands(run)} onClose={onClose} />)
    await userEvent.type(screen.getByLabelText('Search commands'), 'queue')
    await userEvent.keyboard('{Enter}')
    expect(run).toHaveBeenCalledOnce()
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('moves the cursor with the arrow keys', async () => {
    render(<CommandPalette commands={commands()} onClose={() => {}} />)
    await userEvent.keyboard('{ArrowDown}')
    const selected = screen.getAllByRole('button').filter((b) => b.getAttribute('aria-current'))
    expect(selected).toHaveLength(1)
    expect(selected[0]).toHaveTextContent('Queue')
  })

  it('does not run past the end of the list', async () => {
    render(<CommandPalette commands={commands()} onClose={() => {}} />)
    for (let i = 0; i < 20; i++) await userEvent.keyboard('{ArrowDown}')
    const selected = screen.getAllByRole('button').filter((b) => b.getAttribute('aria-current'))
    expect(selected).toHaveLength(1)
  })

  it('closes on Escape', async () => {
    const onClose = vi.fn()
    render(<CommandPalette commands={commands()} onClose={onClose} />)
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('says so plainly when nothing matches', async () => {
    render(<CommandPalette commands={commands()} onClose={() => {}} />)
    await userEvent.type(screen.getByLabelText('Search commands'), 'zzzzz')
    expect(screen.getByText('Nothing matches.')).toBeInTheDocument()
  })

  it('restores focus to where the operator was', () => {
    const trigger = document.createElement('button')
    document.body.appendChild(trigger)
    trigger.focus()
    const { unmount } = render(<CommandPalette commands={commands()} onClose={() => {}} />)
    expect(document.activeElement).not.toBe(trigger)
    unmount()
    expect(document.activeElement).toBe(trigger)
    trigger.remove()
  })
})
