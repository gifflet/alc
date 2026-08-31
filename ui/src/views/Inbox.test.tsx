import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Inbox } from './Inbox'
import { installFetch, renderWithProviders } from '../test/utils'
import { uiStore } from '../app/uiStore'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

const FAILURE = {
  kind: 'failure',
  id: 'failure:v1-01-impl-aaa',
  title: 'add the changelog entry',
  reason: 'failed at chore: check(s) pytest',
  stem: 'v1-01-impl-aaa',
  retries: 1,
}
const BRANCH = {
  kind: 'branch',
  id: 'branch:alc/run-a1b2c3d4',
  title: 'alc/run-a1b2c3d4',
  reason: 'run work ready to land',
  branch: 'alc/run-a1b2c3d4',
  committed_at: 1783828900,
}
const LOOP = {
  kind: 'loop',
  id: 'loop:sweep',
  title: 'sweep',
  reason: 'budget exhausted: usd',
  loop: 'sweep',
  cycle: 7,
}

describe('Inbox', () => {
  it('says so plainly when nothing needs a human', async () => {
    installFetch({ '/inbox': { items: [], count: 0 } })
    renderWithProviders(<Inbox />)
    expect(await screen.findByText(/Nothing needs you/)).toBeInTheDocument()
  })

  it('states each item and why it needs attention', async () => {
    installFetch({ '/inbox': { items: [FAILURE, LOOP, BRANCH], count: 3 } })
    renderWithProviders(<Inbox />)

    expect(await screen.findByText('add the changelog entry')).toBeInTheDocument()
    // The reason names the gate, never generic prose.
    expect(screen.getByText('failed at chore: check(s) pytest')).toBeInTheDocument()
    expect(screen.getByText('budget exhausted: usd')).toBeInTheDocument()
    expect(screen.getByText('run work ready to land')).toBeInTheDocument()
  })

  it('offers the action that resolves each kind, and only that action', async () => {
    installFetch({ '/inbox': { items: [FAILURE, LOOP, BRANCH], count: 3 } })
    renderWithProviders(<Inbox />)

    expect(await screen.findByRole('button', { name: /Retry/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Land/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Discard/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Open loop/ })).toBeInTheDocument()
    // No dismiss: an item leaves by being acted on, never by being hidden.
    expect(screen.queryByRole('button', { name: /Dismiss/ })).toBeNull()
  })

  it('retries the exact failed stem', async () => {
    const mock = installFetch({
      '/inbox': { items: [FAILURE], count: 1 },
      '/queue/retry': { requeued: ['v1-01-impl-aaa'] },
    })
    renderWithProviders(<Inbox />)
    await userEvent.click(await screen.findByRole('button', { name: /Retry/ }))

    const call = mock.calls.find((c) => c.url.includes('/queue/retry'))
    expect(call?.method).toBe('POST')
    expect(call?.body).toEqual({ stem: 'v1-01-impl-aaa' })
  })

  it('lands the exact branch', async () => {
    const mock = installFetch({
      '/inbox': { items: [BRANCH], count: 1 },
      '/branches/land': { landed: ['alc/run-a1b2c3d4'] },
    })
    renderWithProviders(<Inbox />)
    await userEvent.click(await screen.findByRole('button', { name: /Land/ }))
    // Land now confirms before merging: losing an agent's branch is cheap,
    // unwinding a merge into your own history is not. Scope to the dialog, since
    // the row's button carries the same word.
    const confirm = await screen.findByRole('dialog')
    await userEvent.click(within(confirm).getByRole('button', { name: 'Land' }))

    const call = mock.calls.find((c) => c.url.includes('/branches/land'))
    expect(call?.body).toEqual({ branches: ['alc/run-a1b2c3d4'] })
  })

  it('confirms before discarding, naming the consequence', async () => {
    const mock = installFetch({
      '/inbox': { items: [BRANCH], count: 1 },
      '/branches/discard': { deleted: ['alc/run-a1b2c3d4'] },
    })
    renderWithProviders(<Inbox />)
    await userEvent.click(await screen.findByRole('button', { name: /Discard/ }))

    // Nothing is sent until the operator confirms.
    expect(mock.calls.find((c) => c.url.includes('/branches/discard'))).toBeUndefined()
    expect(screen.getByText(/force-deletes the branch/)).toBeInTheDocument()

    // Two "Discard" buttons exist now (the row's and the dialog's) — confirm
    // through the dialog specifically.
    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Discard' }))
    expect(mock.calls.find((c) => c.url.includes('/branches/discard'))?.body).toEqual({
      branches: ['alc/run-a1b2c3d4'],
    })
  })

  it('opens the loop tab from a halted loop', async () => {
    installFetch({ '/inbox': { items: [LOOP], count: 1 } })
    renderWithProviders(<Inbox />)
    await userEvent.click(await screen.findByRole('button', { name: /Open loop/ }))
    expect(uiStore.getState().activeTabId).toBe('loop:sweep')
  })
})

describe('Inbox retry already queued', () => {
  const QUEUED = { ...FAILURE, retry_pending: true }

  it('keeps the item, because a queued retry has not fixed anything yet', async () => {
    installFetch({ '/inbox': { items: [QUEUED], count: 1 } })
    renderWithProviders(<Inbox />)
    expect(await screen.findByText('add the changelog entry')).toBeInTheDocument()
    expect(screen.getByText(/a retry is queued, not yet run/)).toBeInTheDocument()
  })

  it('disables the action so the same work is not queued twice', async () => {
    installFetch({ '/inbox': { items: [QUEUED], count: 1 } })
    renderWithProviders(<Inbox />)
    expect(await screen.findByRole('button', { name: /Retry queued/ })).toBeDisabled()
  })
})

describe('Inbox — a branch whose run never passed', () => {
  const unverified = {
    kind: 'branch' as const,
    id: 'branch:alc/run-bad',
    title: 'alc/run-bad',
    reason: 'run work — checks did not pass, review before landing',
    branch: 'alc/run-bad',
    committed_at: 2,
    verified: false,
  }

  it('does not call it ready to land', async () => {
    // The reported case: interrupted run, failing check, committed anyway, and
    // the Inbox said "ready to land" beside a branch that had actually passed.
    installFetch({ '/inbox': { items: [unverified], count: 1 } })
    renderWithProviders(<Inbox />)

    expect(await screen.findByText(/checks did not pass/)).toBeInTheDocument()
    expect(screen.queryByText(/ready to land/)).not.toBeInTheDocument()
  })

  it('says so in the Land confirmation, where the decision is made', async () => {
    installFetch({ '/inbox': { items: [unverified], count: 1 } })
    renderWithProviders(<Inbox />)

    await userEvent.click(await screen.findByRole('button', { name: /Land/ }))

    expect(await screen.findByText(/checks did NOT pass/)).toBeInTheDocument()
    expect(screen.getByText(/Read the diff first/)).toBeInTheDocument()
  })

  it('still allows landing it — this warns, it does not refuse', async () => {
    const mock = installFetch({
      '/inbox': { items: [unverified], count: 1 },
      '/branches/land': { merged: ['alc/run-bad'], left: [] },
    })
    renderWithProviders(<Inbox />)

    await userEvent.click(await screen.findByRole('button', { name: /Land/ }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Land' }))

    await waitFor(() =>
      expect(mock.calls.some((c) => c.method === 'POST' && c.url.includes('/branches/land'))).toBe(
        true,
      ),
    )
  })

  it('leaves a verified branch reading exactly as before', async () => {
    installFetch({
      '/inbox': {
        items: [{ ...unverified, id: 'branch:alc/run-ok', title: 'alc/run-ok',
                  branch: 'alc/run-ok', reason: 'run work ready to land', verified: true }],
        count: 1,
      },
    })
    renderWithProviders(<Inbox />)

    expect(await screen.findByText('run work ready to land')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: /Land/ })[0])
    expect(await screen.findByText(/merges the agent's commits/)).toBeInTheDocument()
  })
})

describe('Inbox — the badge must agree with the sentence', () => {
  it('does not print TO LAND beside "checks did not pass"', async () => {
    installFetch({
      '/inbox': {
        items: [{
          kind: 'branch' as const, id: 'branch:alc/run-bad', title: 'alc/run-bad',
          reason: 'run work — checks did not pass, review before landing',
          branch: 'alc/run-bad', committed_at: 2, verified: false,
        }],
        count: 1,
      },
    })
    renderWithProviders(<Inbox />)

    expect(await screen.findByText('unverified')).toBeInTheDocument()
    expect(screen.queryByText('to land')).not.toBeInTheDocument()
  })
})
