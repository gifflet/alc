import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RunOutcome } from './RunOutcome'

const base = { finished: true, success: true, aborted: false, commitSha: 'abc1234' }

describe('RunOutcome', () => {
  it('says the checks passed, in those words', () => {
    render(<RunOutcome {...base} />)
    expect(screen.getByText(/checks passed/)).toBeInTheDocument()
  })

  it('points at the diff, because that is the part ALC does not verify', () => {
    render(<RunOutcome {...base} />)
    // The product guarantees the change compiles and the checks pass — not that
    // it is right. A beginner who is not told this trusts it too far.
    expect(screen.getByText(/did not verify that/)).toBeInTheDocument()
    expect(screen.getByText(/Read the diff/)).toBeInTheDocument()
  })

  it('says plainly that nothing was committed when the checks failed', () => {
    render(<RunOutcome {...base} success={false} />)
    expect(screen.getByText(/checks did not pass/)).toBeInTheDocument()
    expect(screen.getByText(/was not committed and was not merged/)).toBeInTheDocument()
  })

  it('warns that edits may remain when a run was stopped', () => {
    render(<RunOutcome {...base} aborted />)
    expect(screen.getByText(/Stopped before finishing/)).toBeInTheDocument()
    expect(screen.getByText(/still in the working tree/)).toBeInTheDocument()
  })

  it('promises the checks while still running, without claiming a result', () => {
    render(<RunOutcome finished={false} success={null} aborted={false} />)
    expect(screen.getByText(/nothing is reported done before they pass/)).toBeInTheDocument()
    expect(screen.queryByText(/checks passed/)).not.toBeInTheDocument()
  })

  it('uses no vocabulary a newcomer would have to look up', () => {
    render(<RunOutcome {...base} />)
    for (const term of ['Assurance Loop', 'Scorecard', 'Single Mandate', 'Blueprint', 'span']) {
      expect(screen.queryByText(new RegExp(term))).not.toBeInTheDocument()
    }
  })
})

describe('RunOutcome — reading the diff', () => {
  it('offers no button when the run left no branch to read', () => {
    // A run against the working tree has no diff of its own; a button here would
    // open nothing.
    render(<RunOutcome finished success aborted={false} onSeeChanges={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /See what changed/ })).not.toBeInTheDocument()
  })

  it('opens the branch it actually committed on', () => {
    const seen = vi.fn()
    render(
      <RunOutcome finished success aborted={false} branch="alc/run-ab12cd34" onSeeChanges={seen} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /See what changed/ }))
    expect(seen).toHaveBeenCalledWith('alc/run-ab12cd34')
  })

  it('stays quiet on a failure — there is nothing landed to review', () => {
    render(
      <RunOutcome
        finished
        success={false}
        aborted={false}
        branch="alc/run-ab12cd34"
        onSeeChanges={vi.fn()}
      />,
    )
    expect(screen.queryByRole('button', { name: /See what changed/ })).not.toBeInTheDocument()
  })
})
