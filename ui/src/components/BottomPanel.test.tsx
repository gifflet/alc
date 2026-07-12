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
