import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StartWork } from './StartWork'
import { ApiError } from '../api/client'

const start = vi.fn()
vi.mock('../app/useStartExec', () => ({ useStartExec: () => start }))

describe('StartWork', () => {
  const field = () => screen.getByLabelText('What should the agent work on?')

  it('will not start on an empty goal', () => {
    render(<StartWork />)
    expect(screen.getByRole('button', { name: /Start/ })).toBeDisabled()
  })

  it('sends the goal to the conductor and nothing else', async () => {
    start.mockResolvedValue('e1')
    render(<StartWork />)
    fireEvent.change(field(), { target: { value: 'fix the missing config crash' } })
    fireEvent.click(screen.getByRole('button', { name: /Start/ }))

    // Engine and tier are on file in the manifest; asking again would be asking
    // a question whose answer the project already gave.
    await waitFor(() =>
      expect(start).toHaveBeenCalledWith('conduct', { goal: 'fix the missing config crash' }),
    )
  })

  it('starts on Enter, without reaching for the button', async () => {
    start.mockResolvedValue('e1')
    render(<StartWork />)
    fireEvent.change(field(), { target: { value: 'add a health endpoint' } })
    fireEvent.keyDown(field(), { key: 'Enter' })
    await waitFor(() => expect(start).toHaveBeenCalled())
  })

  it('states the guarantee without naming the mechanism', () => {
    render(<StartWork />)
    const promise = screen.getByText(/runs this project's checks before/)
    expect(promise).toBeInTheDocument()
    // The value has to be legible to someone who has never read the docs.
    expect(screen.queryByText(/Assurance Loop/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Blueprint/)).not.toBeInTheDocument()
  })

  it('clears the field after a successful start', async () => {
    start.mockResolvedValue('e1')
    render(<StartWork />)
    fireEvent.change(field(), { target: { value: 'something' } })
    fireEvent.click(screen.getByRole('button', { name: /Start/ }))
    await waitFor(() => expect(field()).toHaveValue(''))
  })

  it('keeps the goal when starting fails, so it is not retyped', async () => {
    start.mockRejectedValue(new ApiError('no engine configured', 400, null))
    render(<StartWork />)
    fireEvent.change(field(), { target: { value: 'keep me' } })
    fireEvent.click(screen.getByRole('button', { name: /Start/ }))
    await waitFor(() => expect(screen.getByText(/no engine configured/)).toBeInTheDocument())
    expect(field()).toHaveValue('keep me')
  })
})
