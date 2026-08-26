import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { useApplyDensity, useDensity } from './useDensity'
import { uiStore } from './uiStore'
import { clearMatchMedia, mockMatchMedia } from '../test/utils'

function Probe() {
  const density = useApplyDensity()
  return <span data-testid="density">{density}</span>
}

function ReadProbe() {
  return <span data-testid="density">{useDensity()}</span>
}

beforeEach(() => {
  uiStore.setDensity(null)
})

afterEach(() => {
  clearMatchMedia()
  uiStore.setDensity(null)
  delete document.documentElement.dataset.density
})

describe('useDensity', () => {
  it('resolves to compact on a mouse-driven wide screen', () => {
    mockMatchMedia([])
    const { getByTestId } = render(<ReadProbe />)
    expect(getByTestId('density')).toHaveTextContent('compact')
  })

  it('resolves to cozy for a tablet (coarse pointer, not narrow, not wide)', () => {
    // The defect this fixes: an iPad landed on phone density inside the desktop
    // IDE grid — 44px rows in a layout built for a mouse.
    mockMatchMedia(['pointer: coarse'])
    const { getByTestId } = render(<ReadProbe />)
    expect(getByTestId('density')).toHaveTextContent('cozy')
  })

  it('keeps a wide touchscreen compact — its operator is at a keyboard', () => {
    mockMatchMedia(['pointer: coarse', 'min-width: 1280px'])
    const { getByTestId } = render(<ReadProbe />)
    expect(getByTestId('density')).toHaveTextContent('compact')
  })

  it('resolves to comfortable for a narrow viewport', () => {
    mockMatchMedia(['max-width: 767px'])
    const { getByTestId } = render(<ReadProbe />)
    expect(getByTestId('density')).toHaveTextContent('comfortable')
  })

  it('honours an explicit override over detection', () => {
    mockMatchMedia(['pointer: coarse', 'max-width: 767px'])
    uiStore.setDensity('compact')
    const { getByTestId } = render(<ReadProbe />)
    expect(getByTestId('density')).toHaveTextContent('compact')
  })

  it('degrades to compact when the host has no matchMedia', () => {
    clearMatchMedia()
    const { getByTestId } = render(<ReadProbe />)
    expect(getByTestId('density')).toHaveTextContent('compact')
  })

  it('writes the resolved density onto the document element', () => {
    mockMatchMedia(['max-width: 767px'])
    render(<Probe />)
    expect(document.documentElement.dataset.density).toBe('comfortable')
  })
})

/*
 * The compact values are the desktop contract. They started as the sizes
 * hardcoded inside the components (28/24/12/11); move 8 raised them after
 * measuring the result on screen. That change was deliberate — this test
 * exists to stop the NEXT one from being accidental.
 *
 * vitest runs with `css: false`, so getComputedStyle cannot resolve a custom
 * property here — asserting the stylesheet's declared values is the honest
 * check, and it is what actually guards against an accidental edit.
 */
describe('density token contract', () => {
  // vitest's root is ui/ (its config lives there), so the stylesheet is read
  // from the project root rather than through import.meta.url, which vitest
  // does not expose as a file: URL. `?raw` is not an option either: the suite
  // runs with `css: false`, which yields an empty module.
  const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')
  // Bound to the density declaration itself: a light-theme block now sits
  // between ':root {' and the comfortable block, and a loose slice would let a
  // token defined elsewhere satisfy this assertion.
  const densityStart = css.indexOf('--ui-row-h')
  const compactBlock = css.slice(densityStart, css.indexOf("[data-density='comfortable']"))

  it.each([
    ['--ui-row-h', '32px'],
    ['--ui-control-h', '28px'],
    ['--ui-rail-btn', '40px'],
    ['--ui-text-body', '13px'],
    ['--ui-text-label', '12px'],
    ['--ui-text-title', '14px'],
  ])('pins %s to the agreed desktop value %s', (token, value) => {
    expect(compactBlock).toContain(`${token}: ${value};`)
  })

  it('keeps the rail button at its desktop 40px when compact', () => {
    expect(compactBlock).toContain('--ui-rail-btn: 40px;')
  })

  it('never lets compact fall back below the WCAG 24px target floor', () => {
    // Whatever the aesthetic, a control smaller than 24x24 fails SC 2.5.8.
    const match = compactBlock.match(/--ui-control-h: (\d+)px;/)
    expect(Number(match![1])).toBeGreaterThanOrEqual(24)
  })

  it('gives the tablet scale a 40px target — tappable without phone-sized rows', () => {
    const cozy = css.slice(css.indexOf("[data-density='cozy']"), css.indexOf("[data-density='comfortable']"))
    for (const token of ['--ui-row-h', '--ui-control-h']) {
      const match = cozy.match(new RegExp(`${token}: (\\d+)px;`))
      expect(match, `${token} missing from the cozy block`).not.toBeNull()
      expect(Number(match![1])).toBeGreaterThanOrEqual(40)
    }
  })

  it('raises every interactive target to the 44px touch floor when comfortable', () => {
    const roomy = css.slice(css.indexOf("[data-density='comfortable']"))
    for (const token of ['--ui-row-h', '--ui-control-h']) {
      const match = roomy.match(new RegExp(`${token}: (\\d+)px;`))
      expect(match, `${token} missing from the comfortable block`).not.toBeNull()
      expect(Number(match![1])).toBeGreaterThanOrEqual(44)
    }
  })
})
