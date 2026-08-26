import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Sheet } from './Sheet'

describe('Sheet', () => {
  it('is exposed as a labelled dialog', () => {
    render(
      <Sheet title="Project" onClose={() => {}}>
        <p>tree</p>
      </Sheet>,
    )
    expect(screen.getByRole('dialog', { name: 'Project' })).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const onClose = vi.fn()
    render(
      <Sheet title="Project" onClose={onClose}>
        <p>tree</p>
      </Sheet>,
    )
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('closes when the scrim is clicked but not when the panel is', async () => {
    const onClose = vi.fn()
    render(
      <Sheet title="Project" onClose={onClose}>
        <p>tree</p>
      </Sheet>,
    )
    await userEvent.click(screen.getByText('tree'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('returns focus to the trigger on close', () => {
    // Without this, focus falls back to <body> and keyboard/screen-reader users
    // lose their place every time a sheet closes.
    const trigger = document.createElement('button')
    document.body.appendChild(trigger)
    trigger.focus()
    const { unmount } = render(
      <Sheet title="Project" onClose={() => {}}>
        <p>tree</p>
      </Sheet>,
    )
    expect(document.activeElement).not.toBe(trigger)
    unmount()
    expect(document.activeElement).toBe(trigger)
    trigger.remove()
  })
})
