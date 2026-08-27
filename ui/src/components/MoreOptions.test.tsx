import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MoreOptions } from './MoreOptions'

describe('MoreOptions', () => {
  it('starts closed, so the form asks one question rather than four', () => {
    render(
      <MoreOptions>
        <p>an option</p>
      </MoreOptions>,
    )
    expect(screen.queryByText('an option')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Options/ })).toHaveAttribute('aria-expanded', 'false')
  })

  it('opens in one click — collapsed is not removed', () => {
    render(
      <MoreOptions>
        <p>an option</p>
      </MoreOptions>,
    )
    fireEvent.click(screen.getByRole('button', { name: /Options/ }))
    expect(screen.getByText('an option')).toBeInTheDocument()
  })

  it('names what is inside while it is shut', () => {
    render(
      <MoreOptions hint="engine, compute tier, isolation">
        <p>an option</p>
      </MoreOptions>,
    )
    // A disclosure that does not say what it hides is a disclosure nobody opens.
    expect(screen.getByText(/engine, compute tier, isolation/)).toBeInTheDocument()
  })
})
