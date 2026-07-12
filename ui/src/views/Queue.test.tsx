import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Queue } from './Queue'
import { installFetch, renderWithProviders } from '../test/utils'
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
