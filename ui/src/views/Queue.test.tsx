import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Queue } from './Queue'
import { installFetch, renderWithProviders, res } from '../test/utils'
import type { FetchCall } from '../test/utils'
import type { Branch, FlowReport, QueueTask, Signal } from '../api/types'

const task: QueueTask = {
  flow: 'ship',
  task: 'add a login page\nmore detail',
  engine: null,
  isolate: true,
  kind: 'flow',
  name: null,
  retries: 0,
  retry_of: null,
  id: null,
  depends_on: [],
}

const report: FlowReport = {
  flow: 'ship',
  engine: 'mock',
  success: true,
  stages: [],
  scorecard: { span: 2, passes: 1, streak: 1, touch: 0 },
  commit_sha: 'abcdef1234',
}

beforeEach(() => {
  localStorage.clear()
})

describe('Queue', () => {
  it('renders pending and done tasks', async () => {
    installFetch({
      '/queue': {
        pending: [{ stem: 'p1', mtime: 1783828795, task }],
        done: [{ stem: 'd1', mtime: 1783828700, task, report }],
      },
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)
    // The task first line shows in both the pending and the done row.
    expect((await screen.findAllByText('add a login page')).length).toBe(2)
    expect(screen.getByText('ship')).toBeInTheDocument()
    expect(screen.getByText('ok')).toBeInTheDocument()
  })

  it('shows the retry attempt badge and reveals the carried feedback on expand', async () => {
    const retried: QueueTask = {
      ...task,
      task: 'add a login page\n\n--- retry feedback ---\nthe smoke check failed: boom',
      retries: 2,
      retry_of: 'ship-root',
    }
    installFetch({
      '/queue': { pending: [{ stem: 'p1', mtime: 1, task: retried }], done: [] },
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)
    // The attempt number is surfaced as a badge.
    expect(await screen.findByText('retry #2')).toBeInTheDocument()
    // Expanding the pending row reveals the full body incl. the carried feedback.
    await userEvent.click(screen.getByText('add a login page'))
    expect(await screen.findByText(/the smoke check failed: boom/)).toBeInTheDocument()
  })

  it('expands a done row to reveal the report summary', async () => {
    installFetch({
      '/queue': {
        pending: [],
        done: [{ stem: 'd1', mtime: 1783828700, task, report }],
      },
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)
    const row = await screen.findByText('add a login page')
    await userEvent.click(row)
    expect(await screen.findByText(/engine: mock/)).toBeInTheDocument()
    expect(screen.getByText(/commit: abcdef1234/)).toBeInTheDocument()
  })
})

const failed: FlowReport = { ...report, success: false }

describe('Queue actions', () => {
  it('enqueues a task from the dialog', async () => {
    const mock = installFetch({
      '/queue/retry': { enqueued: [] },
      '/queue': (call: FetchCall) =>
        call.method === 'POST' ? { stem: 'new' } : { pending: [], done: [] },
      '/flows': [{ name: 'ship', mtime: 1 }],
      '/specialists': [],
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    await userEvent.click(await screen.findByRole('button', { name: /Enqueue task/ }))
    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'do the thing' } })
    await userEvent.click(screen.getByRole('button', { name: 'Enqueue' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/queue'))
    expect(post?.body).toMatchObject({ kind: 'flow', name: 'ship', task: 'do the thing', isolate: true })
  })

  it('enqueues a batch of tasks sharing kind/unit/isolate, one per line', async () => {
    const mock = installFetch({
      '/queue/batch': { stems: ['new-1', 'new-2'] },
      '/queue/retry': { enqueued: [] },
      '/queue': { pending: [], done: [] },
      '/flows': [{ name: 'ship', mtime: 1 }],
      '/specialists': [],
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    await userEvent.click(await screen.findByRole('button', { name: /Enqueue task/ }))
    await userEvent.selectOptions(screen.getByLabelText('Mode'), 'batch')
    fireEvent.change(screen.getByLabelText(/Tasks \(one per line\)/), {
      target: { value: 'first task\nsecond task' },
    })
    await userEvent.click(screen.getByRole('button', { name: /Enqueue 2/ }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/queue/batch'))
    expect(post?.body).toEqual({
      tasks: [
        { kind: 'flow', name: 'ship', task: 'first task', isolate: true },
        { kind: 'flow', name: 'ship', task: 'second task', isolate: true },
      ],
    })
  })

  it('retries a single failure', async () => {
    const mock = installFetch({
      '/queue/retry': { enqueued: ['ship-x'] },
      '/queue': {
        pending: [],
        done: [{ stem: 'd1', mtime: 1, task, report: failed, outstanding: true }],
      },
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    await userEvent.click(await screen.findByRole('button', { name: 'Retry d1' }))
    const retry = mock.calls.find((c) => c.url.includes('/queue/retry'))
    expect(retry?.body).toEqual({ stem: 'd1' })
  })

  it('retries all failures from the header', async () => {
    const mock = installFetch({
      '/queue/retry': { enqueued: ['ship-x'] },
      '/queue': {
        pending: [],
        done: [{ stem: 'd1', mtime: 1, task, report: failed, outstanding: true }],
      },
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    await userEvent.click(await screen.findByRole('button', { name: /Retry all failures/ }))
    const retry = mock.calls.find((c) => c.url.includes('/queue/retry'))
    expect(retry?.body).toEqual({ all: true })
  })

  it('offers no retry on a failure already resolved by a later attempt', async () => {
    // report.success=false but NOT outstanding (a later retry in its lineage
    // succeeded) -> no retry button and no "Retry all" (retry all would re-enqueue
    // nothing). This matches what `alc retry` actually does.
    installFetch({
      '/queue/retry': { enqueued: [] },
      '/queue': {
        pending: [],
        done: [{ stem: 'd1', mtime: 1, task, report: failed, outstanding: false }],
      },
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)
    expect(await screen.findByText('failed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry d1' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Retry all failures/ })).not.toBeInTheDocument()
  })

  it('deletes a pending task after confirmation', async () => {
    const mock = installFetch({
      '/queue/retry': { enqueued: [] },
      '/queue': (call: FetchCall) =>
        call.method === 'DELETE'
          ? res(204, {})
          : { pending: [{ stem: 'p1', mtime: 1, task }], done: [] },
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    await userEvent.click(await screen.findByRole('button', { name: 'Delete p1' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    const del = mock.calls.find((c) => c.method === 'DELETE')
    expect(del?.url).toContain('/queue/p1')
  })
})

// verified is null on purpose: a tick branch archives no branch-named report,
// so the absence of one proves nothing about it.
const branch: Branch = {
  name: 'alc/tick-aaaaaaaa',
  label: 'tick',
  committed_at: 1,
  merged: false,
  verified: null,
}

describe('Branches', () => {
  it('lists unmerged alc/* branches and lands one', async () => {
    const mock = installFetch({
      '/queue': { pending: [], done: [] },
      '/branches/land': { merged: ['alc/tick-aaaaaaaa'], conflicted: [] },
      '/branches': { available: true, branches: [branch] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    expect(await screen.findByText('alc/tick-aaaaaaaa')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Land alc/tick-aaaaaaaa' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/branches/land'))
    expect(post?.body).toEqual({ branches: ['alc/tick-aaaaaaaa'] })
  })

  it('discards a branch only after confirmation', async () => {
    const mock = installFetch({
      '/queue': { pending: [], done: [] },
      '/branches/discard': { deleted: ['alc/tick-aaaaaaaa'], pruned_worktrees: 0, deleted_bundles: [] },
      '/branches': { available: true, branches: [branch] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    await screen.findByText('alc/tick-aaaaaaaa')
    await userEvent.click(screen.getByRole('button', { name: 'Discard alc/tick-aaaaaaaa' }))

    // The mutation must not fire before the confirm dialog is accepted.
    expect(
      mock.calls.some((c) => c.method === 'POST' && c.url.endsWith('/branches/discard')),
    ).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/branches/discard'))
    expect(post?.body).toEqual({ branches: ['alc/tick-aaaaaaaa'] })
  })

  it('discards with worktrees pruning and bundle GC when both are checked', async () => {
    const mock = installFetch({
      '/queue': { pending: [], done: [] },
      '/branches/discard': {
        deleted: ['alc/tick-aaaaaaaa'],
        pruned_worktrees: 1,
        deleted_bundles: ['old.jsonl'],
      },
      '/branches': { available: true, branches: [branch] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    await screen.findByText('alc/tick-aaaaaaaa')
    await userEvent.click(screen.getByRole('button', { name: 'Discard alc/tick-aaaaaaaa' }))

    await userEvent.click(screen.getByLabelText('Also prune orphaned git worktrees'))
    await userEvent.click(screen.getByLabelText(/Also delete bundle files older than/))
    fireEvent.change(screen.getByPlaceholderText('30'), { target: { value: '45' } })
    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/branches/discard'))
    expect(post?.body).toEqual({
      branches: ['alc/tick-aaaaaaaa'],
      worktrees: true,
      bundles: { older_than_days: 45 },
    })
  })

  it('shows a clear empty state outside a git repository', async () => {
    installFetch({
      '/queue': { pending: [], done: [] },
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    expect(await screen.findByText(/not inside a git repository/i)).toBeInTheDocument()
  })

  it('surfaces a conflicted branch left by a partial land', async () => {
    installFetch({
      '/queue': { pending: [], done: [] },
      '/branches/land': { merged: [], conflicted: ['alc/tick-aaaaaaaa'] },
      '/branches': { available: true, branches: [branch] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    await userEvent.click(await screen.findByRole('button', { name: 'Land alc/tick-aaaaaaaa' }))

    const note = await screen.findByText(/left for manual resolution/i)
    expect(note.textContent).toContain('alc/tick-aaaaaaaa')
  })

  it('sends the chosen delivery mode when landing', async () => {
    const mock = installFetch({
      '/queue': { pending: [], done: [] },
      '/branches/land': { merged: ['alc/tick-aaaaaaaa'], conflicted: [], warning: null },
      '/branches': { available: true, branches: [branch] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    await screen.findByText('alc/tick-aaaaaaaa')
    await userEvent.selectOptions(screen.getByRole('combobox'), 'push')
    await userEvent.click(screen.getByRole('button', { name: 'Land alc/tick-aaaaaaaa' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/branches/land'))
    expect(post?.body).toEqual({ branches: ['alc/tick-aaaaaaaa'], mode: 'push' })
  })

  it('surfaces a delivery warning from a push/PR attempt without hiding the merge', async () => {
    installFetch({
      '/queue': { pending: [], done: [] },
      '/branches/land': {
        merged: ['alc/tick-aaaaaaaa'],
        conflicted: [],
        warning: 'git push origin main failed: no such remote',
      },
      '/branches': { available: true, branches: [branch] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    await screen.findByText('alc/tick-aaaaaaaa')
    await userEvent.selectOptions(screen.getByRole('combobox'), 'pr')
    await userEvent.click(screen.getByRole('button', { name: 'Land alc/tick-aaaaaaaa' }))

    expect(await screen.findByText(/no such remote/i)).toBeInTheDocument()
  })
})

const signal: Signal = {
  path: '/proj/.alc/signals/s1.json',
  kind: 'error',
  source: 'sentry',
  title: 'NPE in checkout',
  body: '',
  ts: 1783828795,
  weight: null,
}

describe('Signals', () => {
  it('lists pending signals (kind, source, title, age)', async () => {
    installFetch({
      '/queue': { pending: [], done: [] },
      '/branches': { available: false, branches: [] },
      '/signals': [signal],
    })
    renderWithProviders(<Queue />)

    expect(await screen.findByText('NPE in checkout')).toBeInTheDocument()
    expect(screen.getByText('sentry')).toBeInTheDocument()
    expect(screen.getByText('error')).toBeInTheDocument()
  })

  it('shows a clear empty state with no pending signals', async () => {
    installFetch({
      '/queue': { pending: [], done: [] },
      '/branches': { available: false, branches: [] },
      '/signals': [],
    })
    renderWithProviders(<Queue />)

    expect(await screen.findByText(/no pending signals/i)).toBeInTheDocument()
  })

  it('ingests a signal from the dialog with the exact payload', async () => {
    const mock = installFetch({
      '/queue': { pending: [], done: [] },
      '/branches': { available: false, branches: [] },
      '/signals': (call: FetchCall) => (call.method === 'POST' ? { path: '/proj/.alc/signals/s2.json' } : []),
    })
    renderWithProviders(<Queue />)

    await userEvent.click(await screen.findByRole('button', { name: 'Ingest signal' }))
    fireEvent.change(screen.getByLabelText('Kind'), { target: { value: 'feedback' } })
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'operator' } })
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'slow onboarding' } })
    fireEvent.change(screen.getByLabelText('Body'), { target: { value: 'users drop off at step 2' } })
    await userEvent.click(screen.getByRole('button', { name: 'Ingest' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/signals'))
    expect(post?.body).toEqual({
      kind: 'feedback',
      source: 'operator',
      title: 'slow onboarding',
      body: 'users drop off at step 2',
    })
  })
})
