import { beforeEach, describe, expect, it, vi } from 'vitest'
import { authStore } from './authStore'

beforeEach(() => authStore.setUnauthorized(false))

describe('authStore', () => {
  it('starts authorized', () => {
    expect(authStore.getState()).toBe(false)
  })

  it('notifies subscribers when the state flips', () => {
    const listener = vi.fn()
    const off = authStore.subscribe(listener)
    authStore.setUnauthorized(true)
    expect(listener).toHaveBeenCalledTimes(1)
    expect(authStore.getState()).toBe(true)
    off()
  })

  it('does not notify on a repeated identical value', () => {
    authStore.setUnauthorized(true)
    const listener = vi.fn()
    const off = authStore.subscribe(listener)
    authStore.setUnauthorized(true)
    expect(listener).not.toHaveBeenCalled()
    off()
  })
})
