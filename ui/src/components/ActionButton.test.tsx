import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ActionButton } from './ActionButton'

describe('ActionButton', () => {
  it('always carries the density floor, so no call site can forget it', () => {
    // The whole reason this component exists: the floor stops being a decision
    // made once per button.
    render(<ActionButton>Go</ActionButton>)
    expect(screen.getByRole('button').className).toContain('min-h-[var(--ui-control-h)]')
  })

  it('keeps padding as well as the floor — they are not substitutes', () => {
    // Padding gives the button its proportion; the floor only guarantees it is
    // never smaller than a finger. Replacing one with the other is what broke
    // the Hire row.
    const { container } = render(<ActionButton>Go</ActionButton>)
    const cls = (container.firstChild as HTMLElement).className
    expect(cls).toMatch(/px-\d/)
    expect(cls).toMatch(/py-\d/)
  })

  it('carries the tone it was asked for', () => {
    render(<ActionButton tone="error">Delete</ActionButton>)
    expect(screen.getByRole('button').className).toContain('text-error')
  })

  it('is quieter at sm, without shrinking the target', () => {
    render(<ActionButton size="sm">Retry</ActionButton>)
    const cls = screen.getByRole('button').className
    expect(cls).toContain('var(--ui-text-label)')
    expect(cls).toContain('min-h-[var(--ui-control-h)]')
  })

  it('fires and honours disabled', () => {
    const onClick = vi.fn()
    const { rerender } = render(<ActionButton onClick={onClick}>Go</ActionButton>)
    fireEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledTimes(1)

    rerender(
      <ActionButton onClick={onClick} disabled>
        Go
      </ActionButton>,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
