import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BottomPanel } from './BottomPanel'
import { installFetch, renderWithProviders } from '../test/utils'
import { uiStore } from '../app/uiStore'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  installFetch({
    '/lint': {
      violations: [
        { rule: 'blueprint_has_checks', severity: 'error', message: "Blueprint 'chore' declares no checks." },
        { rule: 'blueprint_has_report', severity: 'warn', message: "Blueprint 'chore' has no report spec." },
      ],
    },
  })
})

describe('Problems panel', () => {
  it('lists lint violations and opens the related file on click', async () => {
    renderWithProviders(<BottomPanel />)
    await userEvent.click(screen.getByRole('button', { name: /Problems/ }))

    const row = await screen.findByText("Blueprint 'chore' declares no checks.")
    await userEvent.click(row)

    const tabs = uiStore.getState().tabs
    expect(tabs.map((t) => t.id)).toContain('source:blueprints:chore')
  })

  it('badges the Problems tab with the error count only', async () => {
    renderWithProviders(<BottomPanel />)
    // One error, one warning -> badge shows 1.
    expect(await screen.findByText('1')).toBeInTheDocument()
  })
})

describe('Problems — what the checks do not reach', () => {
  it('no longer calls a layer clean when it verifies only part of the project', async () => {
    // The CLI's "Operator Layer is conformant" had the same problem: shape and
    // reach are different questions, and only one was being answered.
    installFetch({
      '/lint': {
        violations: [],
        coverage_gaps: ['stacks no check reaches: Node in ui/', 'Nothing verifies that code.'],
      },
    })
    renderWithProviders(<BottomPanel />)
    await userEvent.click(screen.getByRole('button', { name: /Problems/ }))

    expect(await screen.findByText('Not covered')).toBeInTheDocument()
    expect(screen.queryByText(/policy gate is clean/)).not.toBeInTheDocument()
  })

  it('still says clean when there is genuinely nothing to report', async () => {
    // The warning must mean something. A panel that always shows a caveat is a
    // panel nobody reads.
    installFetch({ '/lint': { violations: [], coverage_gaps: [] } })
    renderWithProviders(<BottomPanel />)
    await userEvent.click(screen.getByRole('button', { name: /Problems/ }))

    expect(await screen.findByText(/policy gate is clean/)).toBeInTheDocument()
  })

  it('shows gaps alongside real violations, not instead of them', async () => {
    installFetch({
      '/lint': {
        violations: [{ rule: 'R1', severity: 'error', message: 'a real violation' }],
        coverage_gaps: ['stacks no check reaches: Node in ui/'],
      },
    })
    renderWithProviders(<BottomPanel />)
    await userEvent.click(screen.getByRole('button', { name: /Problems/ }))

    expect(await screen.findByText(/a real violation/)).toBeInTheDocument()
    expect(screen.getByText('Not covered')).toBeInTheDocument()
  })
})
