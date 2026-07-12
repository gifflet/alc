import { describe, expect, it } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import { ConsolePane } from './ConsolePane'

/** Give the (non-layouting) jsdom element realistic scroll geometry. */
function stubGeometry(el: HTMLElement, scrollHeight: number, clientHeight: number): void {
  Object.defineProperty(el, 'scrollHeight', { configurable: true, value: scrollHeight })
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: clientHeight })
}

describe('ConsolePane', () => {
  it('renders lines and an empty state', () => {
    const { rerender, getByText } = render(<ConsolePane lines={[]} />)
    expect(getByText('No output.')).toBeInTheDocument()
    rerender(<ConsolePane lines={['first', 'second']} />)
    expect(getByText('second')).toBeInTheDocument()
  })

  it('auto-scrolls to the bottom as new lines arrive', () => {
    const { container, rerender } = render(<ConsolePane lines={['a']} />)
    const el = container.firstChild as HTMLDivElement
    stubGeometry(el, 100, 10)
    rerender(<ConsolePane lines={['a', 'b']} />)
    expect(el.scrollTop).toBe(100)
  })

  it('pauses auto-scroll when the operator scrolls up, resuming on mouse leave', () => {
    const { container, rerender } = render(<ConsolePane lines={['a']} />)
    const el = container.firstChild as HTMLDivElement
    stubGeometry(el, 100, 10)
    el.scrollTop = 0

    // Hovering + scrolled away from the bottom → paused.
    fireEvent.mouseEnter(el)
    fireEvent.scroll(el)
    el.scrollTop = 5
    rerender(<ConsolePane lines={['a', 'b']} />)
    expect(el.scrollTop).toBe(5) // not yanked to the bottom

    // Leaving the pane resumes auto-scroll.
    fireEvent.mouseLeave(el)
    expect(el.scrollTop).toBe(100)
  })
})
