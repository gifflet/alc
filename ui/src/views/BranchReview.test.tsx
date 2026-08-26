import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BranchReview } from './BranchReview'
import { installFetch, renderWithProviders, res } from '../test/utils'
import { uiStore } from '../app/uiStore'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

const BRANCH = 'alc/run-a1b2c3d4'
const DIFF = `diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,3 @@
 def f():
-    return 1
+    return 2
`

function stub(extra: Record<string, unknown> = {}) {
  return installFetch({
    '/branches/diff': { branch: BRANCH, base: 'main', diff: DIFF, truncated: false },
    '/branches/review': { stem: 'review-notes-abc', comments: 1, branch: BRANCH },
    '/flows': [{ name: 'ship', mtime: 1 }],
    ...extra,
  })
}

describe('BranchReview', () => {
  it('shows the branch diff against its base', async () => {
    stub()
    renderWithProviders(<BranchReview branch={BRANCH} />)
    expect(await screen.findByText(/vs main/)).toBeInTheDocument()
    expect(screen.getByText(/return 2/)).toBeInTheDocument()
  })

  it('refuses to send with no notes', async () => {
    stub()
    renderWithProviders(<BranchReview branch={BRANCH} />)
    expect(await screen.findByRole('button', { name: /Send notes/ })).toBeDisabled()
  })

  it('does not offer a comment anchor on a deleted line', async () => {
    stub()
    renderWithProviders(<BranchReview branch={BRANCH} />)
    await screen.findByText(/return 2/)
    // The post-image has line 2 (the addition); the deletion has no anchor.
    expect(screen.getByLabelText('Comment on app.py:2')).toBeInTheDocument()
    expect(screen.queryByLabelText('Comment on app.py:3')).toBeNull()
  })

  it('writes nothing until the operator submits', async () => {
    const mock = stub()
    renderWithProviders(<BranchReview branch={BRANCH} />)
    await userEvent.click(await screen.findByLabelText('Comment on app.py:2'))
    await userEvent.type(screen.getByLabelText('Note on app.py:2'), 'keep returning 1')
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }))

    expect(mock.calls.find((c) => c.url.includes('/branches/review'))).toBeUndefined()
    expect(screen.getByText('1 note')).toBeInTheDocument()
  })

  it('sends every note anchored to path and line, as one task', async () => {
    const mock = stub()
    renderWithProviders(<BranchReview branch={BRANCH} />)
    await userEvent.click(await screen.findByLabelText('Comment on app.py:2'))
    await userEvent.type(screen.getByLabelText('Note on app.py:2'), 'keep returning 1')
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }))
    await userEvent.click(screen.getByRole('button', { name: /Send notes/ }))

    const call = mock.calls.find((c) => c.url.includes('/branches/review'))
    expect(call?.method).toBe('POST')
    expect(call?.body).toMatchObject({
      branch: BRANCH,
      comments: [{ path: 'app.py', line: 2, text: 'keep returning 1' }],
      // A task with no unit cannot be dispatched by the drain.
      name: 'ship',
      kind: 'flow',
    })
    expect(await screen.findByText(/Queued as review-notes-abc/)).toBeInTheDocument()
  })

  it('clearing a note removes it instead of sending an empty one', async () => {
    stub()
    renderWithProviders(<BranchReview branch={BRANCH} />)
    await userEvent.click(await screen.findByLabelText('Comment on app.py:2'))
    await userEvent.type(screen.getByLabelText('Note on app.py:2'), 'temp')
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }))
    expect(screen.getByText('1 note')).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('Comment on app.py:2'))
    await userEvent.clear(screen.getByLabelText('Note on app.py:2'))
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }))
    expect(screen.getByText('no notes')).toBeInTheDocument()
  })

  it('lands the branch from the same screen', async () => {
    const mock = stub({ '/branches/land': { landed: [BRANCH] } })
    renderWithProviders(<BranchReview branch={BRANCH} />)
    await userEvent.click(await screen.findByRole('button', { name: /Land/ }))
    expect(mock.calls.find((c) => c.url.includes('/branches/land'))?.body).toEqual({
      branches: [BRANCH],
    })
  })

  it('states the reason when the diff cannot be read', async () => {
    installFetch({ '/branches/diff': res(404, { detail: 'no diff available for the branch' }) })
    renderWithProviders(<BranchReview branch={BRANCH} />)
    expect(await screen.findByText(/no diff available/)).toBeInTheDocument()
  })
})

describe('BranchReview unit selection', () => {
  it('will not send when the project has no flow to run the notes as', async () => {
    installFetch({
      '/branches/diff': { branch: BRANCH, base: 'main', diff: DIFF, truncated: false },
      '/flows': [],
    })
    renderWithProviders(<BranchReview branch={BRANCH} />)
    await userEvent.click(await screen.findByLabelText('Comment on app.py:2'))
    await userEvent.type(screen.getByLabelText('Note on app.py:2'), 'note')
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }))
    expect(screen.getByRole('button', { name: /Send notes/ })).toBeDisabled()
  })

  it('lets the operator pick which flow runs the notes', async () => {
    const mock = stub({ '/flows': [{ name: 'ship', mtime: 1 }, { name: 'patrol', mtime: 2 }] })
    renderWithProviders(<BranchReview branch={BRANCH} />)
    await userEvent.click(await screen.findByLabelText('Comment on app.py:2'))
    await userEvent.type(screen.getByLabelText('Note on app.py:2'), 'note')
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }))
    await userEvent.selectOptions(screen.getByLabelText('Flow to run the notes as'), 'patrol')
    await userEvent.click(screen.getByRole('button', { name: /Send notes/ }))

    expect(mock.calls.find((c) => c.url.includes('/branches/review'))?.body).toMatchObject({
      name: 'patrol',
    })
  })
})
