import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StartWork } from './StartWork'
import { ApiError } from '../api/client'
import { installFetch, renderWithProviders } from '../test/utils'

// The guarantee line is derived from the project's engine and checks, so the
// component needs both providers and a fetch that answers those two reads.
const render = (ui: React.ReactElement) => {
  installFetch({
    '/engines': [{ name: 'claude-code', type: 'claude-code', default: true, healthy: true }],
    '/checks/audit': { check_sets: [{ set_name: 'python' }], smoke_only_blueprints: [] },
  })
  return renderWithProviders(ui)
}

const start = vi.fn()
vi.mock('../app/useStartExec', () => ({ useStartExec: () => start }))

describe('StartWork', () => {
  const field = () => screen.getByLabelText('What should the agent work on?')

  it('will not start on an empty goal', () => {
    render(<StartWork />)
    expect(screen.getByRole('button', { name: /Start/ })).toBeDisabled()
  })

  it('runs an isolated chore, so there is a branch to review', async () => {
    start.mockResolvedValue('e1')
    render(<StartWork />)
    fireEvent.change(field(), { target: { value: 'fix the missing config crash' } })
    fireEvent.click(screen.getByRole('button', { name: /Start/ }))

    // isolate is the load-bearing part: conduct's serial path has none, so it
    // edited the working tree and left nothing to review, keep or discard.
    // Engine and tier stay unasked — the manifest has them.
    await waitFor(() =>
      expect(start).toHaveBeenCalledWith('run', {
        blueprint: 'chore',
        task: 'fix the missing config crash',
        isolate: true,
      }),
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
    expect(screen.getByText(/runs this project's own checks before/)).toBeInTheDocument()
    // The value has to be legible to someone who has never read the docs.
    expect(screen.queryByText(/Assurance Loop/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Blueprint/)).not.toBeInTheDocument()
  })

  it('never claims a guarantee the project cannot keep', () => {
    render(<StartWork />)
    // The first version promised "a change that fails them is never reported as
    // finished". A quarantined check fails and the run still succeeds; a
    // smoke-only Blueprint verifies nothing; mock makes no call at all. An
    // absolute claim would be a misreport in each of those states.
    expect(screen.queryByText(/never reported as finished/)).not.toBeInTheDocument()
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

describe('what it tells you before you press it', () => {
  it('says where the change lands, not only that it is verified', () => {
    render(<StartWork />)
    // Promising verification while staying silent about the files is the more
    // dangerous half-truth: someone types into this box the way they type into
    // a search bar, and it edits their repository.
    // Isolated now, so the sentence changed from a warning to a fact — and the
    // fact is what makes "keep it or throw it away" a real choice.
    expect(screen.getByText(/Work happens on a separate branch/)).toBeInTheDocument()
    expect(screen.getByText(/until you decide to keep the result/)).toBeInTheDocument()
  })
})

describe('the guarantee is read, not asserted', () => {
  it('warns instead of promising when the engine is mock', async () => {
    installFetch({
      '/engines': [{ name: 'mock', type: 'mock', default: true, healthy: true }],
      '/checks/audit': { check_sets: [{ set_name: 'python' }], smoke_only_blueprints: [] },
    })
    renderWithProviders(<StartWork />)
    // mock makes no model call. Promising verification here would describe a
    // run that cannot happen.
    await waitFor(() =>
      expect(screen.getByText(/makes no model call, changes nothing/)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/before calling anything done/)).not.toBeInTheDocument()
  })

  it('warns when the only check is a placeholder that always passes', async () => {
    installFetch({
      '/engines': [{ name: 'claude-code', type: 'claude-code', default: true, healthy: true }],
      '/checks/audit': { check_sets: [], smoke_only_blueprints: [{ name: 'chore' }] },
    })
    renderWithProviders(<StartWork />)
    await waitFor(() =>
      expect(screen.getByText(/only a placeholder that always passes/)).toBeInTheDocument(),
    )
  })
})
