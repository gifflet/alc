import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Dialog } from './Dialog'

describe('Dialog sizing', () => {
  it('treats width as a ceiling so it fits a narrow viewport', () => {
    // A fixed 520px dialog overflows a 411px phone (measured on device).
    render(
      <Dialog title="Run" width={520} onClose={() => {}}>
        <p>body</p>
      </Dialog>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog.style.width).toBe('100%')
    expect(dialog.style.maxWidth).toBe('520px')
  })

  it('closes on Escape', async () => {
    const onClose = vi.fn()
    render(
      <Dialog title="Run" width={520} onClose={onClose}>
        <p>body</p>
      </Dialog>,
    )
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('is labelled for assistive technology', () => {
    render(
      <Dialog title="Enqueue" width={520} onClose={() => {}}>
        <p>body</p>
      </Dialog>,
    )
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-label', 'Enqueue')
  })
})
