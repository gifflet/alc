import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RunCost, runCount } from './RunCost'

describe('runCount', () => {
  it('multiplies variants by engines by tiers', () => {
    // The number the operator never saw: five variants across three engines and
    // two tiers is thirty engine turns from one press.
    expect(runCount(5, 3, 2)).toBe(30)
  })

  it('treats nothing-selected as the manifest default, which is one', () => {
    expect(runCount(3, 0, 0)).toBe(3)
    expect(runCount(1, 0, 0)).toBe(1)
  })

  it('never returns zero, because a launch always launches something', () => {
    expect(runCount(0, 0, 0)).toBe(1)
  })
})

describe('RunCost', () => {
  it('says nothing for a single run — a count of one is not news', () => {
    const { container } = render(<RunCost count={1} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('states the number for a small fan-out', () => {
    render(<RunCost count={4} />)
    expect(screen.getByText(/4 runs/)).toBeInTheDocument()
    expect(screen.getByText(/one engine turn each/)).toBeInTheDocument()
  })

  it('escalates the wording once it is a bill, not a comparison', () => {
    render(<RunCost count={30} />)
    expect(screen.getByText(/30 runs/)).toBeInTheDocument()
    expect(screen.getByText(/separate engine turn you pay for/)).toBeInTheDocument()
  })
})
