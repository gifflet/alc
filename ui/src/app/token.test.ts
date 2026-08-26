import { afterEach, describe, expect, it } from 'vitest'
import { clearToken, extractToken, getToken, setToken } from './token'

afterEach(() => {
  clearToken()
  localStorage.clear()
})

describe('extractToken', () => {
  it('takes the token out and removes it from the URL', () => {
    const { token, cleaned } = extractToken('http://host:8642/projects/p?t=secret')
    expect(token).toBe('secret')
    // The secret must not survive in anything the operator could share.
    expect(cleaned).not.toContain('secret')
    expect(cleaned).toBe('/projects/p')
  })

  it('keeps other query parameters and the hash', () => {
    const { cleaned } = extractToken('http://host:8642/x?t=secret&keep=1#frag')
    expect(cleaned).toBe('/x?keep=1#frag')
  })

  it('is a no-op for a URL without a token', () => {
    const href = 'http://host:8642/projects/p'
    expect(extractToken(href)).toEqual({ token: null, cleaned: href })
  })

  it('tolerates a malformed URL', () => {
    expect(extractToken('not a url').token).toBeNull()
  })
})

describe('token storage', () => {
  it('round-trips a token', () => {
    expect(getToken()).toBeNull()
    setToken('abc')
    expect(getToken()).toBe('abc')
    clearToken()
    expect(getToken()).toBeNull()
  })
})
