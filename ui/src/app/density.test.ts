import { describe, expect, it } from 'vitest'
import { resolveDensity } from './density'

describe('resolveDensity', () => {
  // (override, coarsePointer, narrowViewport, wideViewport)
  it('defaults to compact on a mouse-driven wide screen', () => {
    expect(resolveDensity(null, false, false, true)).toBe('compact')
  })

  it('picks comfortable for a phone', () => {
    expect(resolveDensity(null, true, true, false)).toBe('comfortable')
  })

  it('picks comfortable for a narrow viewport even with a fine pointer', () => {
    // A desktop window dragged narrow still gets the phone layout, so its
    // targets must match it.
    expect(resolveDensity(null, false, true, false)).toBe('comfortable')
  })

  it('picks cozy for a tablet: touch, but wide enough for the IDE grid', () => {
    // The defect this fixes: an iPad used to land on phone density inside the
    // desktop grid — 44px rows in a layout built for a mouse.
    expect(resolveDensity(null, true, false, false)).toBe('cozy')
  })

  it('keeps a touchscreen LAPTOP compact', () => {
    // Coarse pointer but 1280px+: the operator is at a keyboard, and ballooning
    // the grid there wastes the screen they chose.
    expect(resolveDensity(null, true, false, true)).toBe('compact')
  })

  it('lets an explicit override win over every rule', () => {
    expect(resolveDensity('compact', true, true, false)).toBe('compact')
    expect(resolveDensity('comfortable', false, false, true)).toBe('comfortable')
    expect(resolveDensity('cozy', false, false, true)).toBe('cozy')
  })
})
