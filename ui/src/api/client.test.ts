import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { api, ApiError } from './client'
import { clearToken, getToken, setToken } from '../app/token'
import { installFetch, res } from '../test/utils'

beforeEach(() => {
  clearToken()
  localStorage.clear()
})
afterEach(() => clearToken())

describe('api token handling', () => {
  it('sends no Authorization header when this browser holds no token', async () => {
    const mock = installFetch({ '/api/projects': [] })
    await api.listProjects()
    // Unauthenticated local use must look exactly as it always has.
    expect(mock.calls[0].headers.authorization).toBeUndefined()
  })

  it('attaches the bearer header once a token is held', async () => {
    setToken('secret')
    const mock = installFetch({ '/api/projects': [] })
    await api.listProjects()
    expect(mock.calls[0].headers.authorization).toBe('Bearer secret')
    expect(mock.calls[0].headers['content-type']).toBe('application/json')
  })

  it('keeps the token out of the request URL', async () => {
    setToken('secret')
    const mock = installFetch({ '/api/projects': [] })
    await api.listProjects()
    expect(mock.calls[0].url).not.toContain('secret')
  })

  it('drops a rejected token so the UI can ask for a fresh one', async () => {
    setToken('stale')
    installFetch({ '/api/projects': res(401, { detail: 'missing or invalid token' }) })
    await expect(api.listProjects()).rejects.toBeInstanceOf(ApiError)
    expect(getToken()).toBeNull()
  })

  it('keeps the token when the failure is not an auth failure', async () => {
    setToken('good')
    installFetch({ '/api/projects': res(500, { detail: 'boom' }) })
    await expect(api.listProjects()).rejects.toBeInstanceOf(ApiError)
    expect(getToken()).toBe('good')
  })
})
