import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Queue } from './Queue'
import { installFetch, renderWithProviders, res } from '../test/utils'
import type { FetchCall } from '../test/utils'
import type { FlowReport, QueueTask } from '../api/types'

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
    installFetch({ '/queue': { pending: [{ stem: 'p1', mtime: 1, task: retried }], done: [] } })
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
    })
    renderWithProviders(<Queue />)

    await userEvent.click(await screen.findByRole('button', { name: /Enqueue task/ }))
    fireEvent.change(await screen.findByLabelText('Task'), { target: { value: 'do the thing' } })
    await userEvent.click(screen.getByRole('button', { name: 'Enqueue' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.endsWith('/queue'))
    expect(post?.body).toMatchObject({ kind: 'flow', name: 'ship', task: 'do the thing', isolate: true })
  })

  it('retries a single failure', async () => {
    const mock = installFetch({
      '/queue/retry': { enqueued: ['ship-x'] },
      '/queue': {
        pending: [],
        done: [{ stem: 'd1', mtime: 1, task, report: failed, outstanding: true }],
      },
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
    })
    renderWithProviders(<Queue />)

    await userEvent.click(await screen.findByRole('button', { name: 'Delete p1' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    const del = mock.calls.find((c) => c.method === 'DELETE')
    expect(del?.url).toContain('/queue/p1')
  })
})
