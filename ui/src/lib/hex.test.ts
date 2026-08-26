import { describe, expect, it } from 'vitest'
import { expandHex } from './hex'

describe('expandHex', () => {
  it('passes a full hex through', () => {
    expect(expandHex('#1b1d1f')).toBe('#1b1d1f')
    expect(expandHex('1b1d1f')).toBe('#1b1d1f')
  })

  it('expands the shorthand CSS serves', () => {
    // getPropertyValue('--color-base') returns "#fff" for #ffffff, and Monaco
    // rejects the shorthand — the editor rendered with no background.
    expect(expandHex('#fff')).toBe('#ffffff')
    expect(expandHex('#abc')).toBe('#aabbcc')
  })

  it('returns null for anything that is not a hex colour', () => {
    expect(expandHex('rgb(1,2,3)')).toBeNull()
    expect(expandHex('')).toBeNull()
  })
})
