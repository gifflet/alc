import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TokenPrompt } from './TokenPrompt'
import { authStore } from '../app/authStore'
import { clearToken, getToken } from '../app/token'

beforeEach(() => {
  clearToken()
  authStore.setUnauthorized(false)
  vi.stubGlobal('location', { ...window.location, reload: vi.fn() })
})
afterEach(() => {
  vi.unstubAllGlobals()
  clearToken()
})

describe('TokenPrompt', () => {
  it('states the cause instead of pretending the project is empty', () => {
    render(<TokenPrompt />)
    expect(screen.getByText('Token required')).toBeInTheDocument()
    expect(screen.getByText(/--token/)).toBeInTheDocument()
  })

  it('stores a pasted token and clears the unauthorized state', async () => {
    authStore.setUnauthorized(true)
    render(<TokenPrompt />)
    await userEvent.type(screen.getByLabelText('API token'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }))
    expect(getToken()).toBe('secret')
    expect(authStore.getState()).toBe(false)
  })

  it('ignores an empty submission', async () => {
    render(<TokenPrompt />)
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }))
    expect(getToken()).toBeNull()
  })

  it('masks the token as it is typed', () => {
    render(<TokenPrompt />)
    expect(screen.getByLabelText('API token')).toHaveAttribute('type', 'password')
  })
})
