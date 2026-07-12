import { describe, expect, it } from 'vitest'
import { relativeTime, formatBytes, formatCount, titleCase } from './format'

describe('relativeTime', () => {
  // mtime values from the backend are epoch SECONDS (Path.stat().st_mtime).
  const now = 1_700_000_000_000 // ms

  it('renders "now" for sub-minute deltas', () => {
    expect(relativeTime(now / 1000 - 5, now)).toBe('now')
  })

  it('renders minutes', () => {
    expect(relativeTime(now / 1000 - 120, now)).toBe('2m ago')
  })

  it('renders hours', () => {
    expect(relativeTime(now / 1000 - 3 * 3600, now)).toBe('3h ago')
  })

  it('renders days', () => {
    expect(relativeTime(now / 1000 - 2 * 86400, now)).toBe('2d ago')
  })

  it('accepts an ISO string', () => {
    const iso = new Date(now - 60_000).toISOString()
    expect(relativeTime(iso, now)).toBe('1m ago')
  })
})

describe('formatBytes', () => {
  it('formats small sizes in bytes', () => {
    expect(formatBytes(712)).toBe('712 B')
  })
  it('formats kilobytes', () => {
    expect(formatBytes(2048)).toBe('2.0 KB')
  })
})

describe('formatCount', () => {
  it('groups thousands', () => {
    expect(formatCount(12345)).toBe('12,345')
  })
})

describe('titleCase', () => {
  it('turns an event name into a label', () => {
    expect(titleCase('mandate_started')).toBe('Mandate started')
  })
})
