import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OperatorShell, destinationFor } from './OperatorShell'
import { uiStore } from './uiStore'
import { clearMatchMedia, installFetch, mockMatchMedia, renderWithProviders } from '../test/utils'
import { WsProvider } from '../ws/WsProvider'

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  mockMatchMedia(['max-width: 767px'])
  installFetch({ '/inbox': { items: [], count: 0 } })
})
afterEach(() => clearMatchMedia())

function renderShell() {
  return renderWithProviders(
    <WsProvider projectId="demo">
      <OperatorShell projectName="demo" onSwitchProject={() => {}} />
    </WsProvider>,
  )
}

describe('destinationFor', () => {
  it('maps a resident view to its own destination', () => {
    expect(destinationFor('view:fleet', false)).toBe('fleet')
    expect(destinationFor('view:inbox', false)).toBe('inbox')
  })

  it('groups every non-resident view under More', () => {
    expect(destinationFor('view:team', false)).toBe('more')
    expect(destinationFor('view:runs', false)).toBe('more')
  })

  it('resolves the project root to its own destination, not More', () => {
    // Opening /projects/:id lands on the Dashboard; the bar used to light "More",
    // telling the operator they were somewhere they were not.
    expect(destinationFor('view:dashboard', false)).toBe('dashboard')
  })

  it('treats a detail tab as no destination, so nothing is falsely highlighted', () => {
    expect(destinationFor('run:some-stem', false)).toBeNull()
  })

  it('reports More while the More list is open', () => {
    expect(destinationFor('view:fleet', true)).toBe('more')
  })
})

describe('OperatorShell', () => {
  it('shows the five phone destinations', async () => {
    renderShell()
    const nav = await screen.findByRole('navigation', { name: 'Destinations' })
    const labels = Array.from(nav.querySelectorAll('button')).map((b) => b.textContent?.trim())
    expect(labels).toEqual(['Home', 'Inbox', 'Fleet', 'Queue', 'More'])
  })

  it('does not render the desktop chrome', () => {
    renderShell()
    // No activity rail, no tab bar, no resizers on a phone.
    expect(screen.queryByLabelText('Run Configurations')).toBeNull()
    expect(screen.queryByLabelText('Spike')).toBeNull()
  })

  it('opens the project tree as a dismissible sheet', async () => {
    renderShell()
    await userEvent.click(screen.getByLabelText('Project tree'))
    const sheet = await screen.findByRole('dialog', { name: 'Project' })
    expect(sheet).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Project' })).toBeNull()
  })

  it('navigates to a destination and marks it current', async () => {
    renderShell()
    await userEvent.click(screen.getByLabelText('Queue'))
    expect(uiStore.getState().activeTabId).toBe('view:queue')
    expect(screen.getByLabelText('Queue')).toHaveAttribute('aria-current', 'page')
  })

  it('shows More without pushing a tab, and Back leaves it', async () => {
    renderShell()
    await userEvent.click(screen.getByLabelText('More'))
    expect(await screen.findByText('Archetype packs and mix health')).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('Back'))
    expect(screen.queryByText('Archetype packs and mix health')).toBeNull()
  })

  it('pops the stack with Back once a second tab is open', async () => {
    renderShell()
    await userEvent.click(screen.getByLabelText('Fleet'))
    act(() => {
      uiStore.openTab({ target: { type: 'run', stem: 'run-a' }, title: 'run-a' })
    })
    expect(uiStore.getState().activeTabId).toBe('run:run-a')

    // Back pops to the previous entry rather than leaving the app.
    await userEvent.click(await screen.findByLabelText('Back'))
    expect(uiStore.getState().activeTabId).toBe('view:fleet')
  })

  it('offers the project switcher when there is nothing to go back to', () => {
    renderShell()
    expect(screen.getByLabelText('Switch project')).toBeInTheDocument()
    expect(screen.queryByLabelText('Back')).toBeNull()
  })
})

describe('OperatorShell — Spike on a phone', () => {
  it('offers Spike from More, the one place a phone can reach an action', async () => {
    // Spike has no bottom tab and no view to open, so without this row the phone
    // simply cannot start one. The desktop rail always could.
    renderShell()

    await userEvent.click(screen.getByRole('button', { name: /More/ }))
    await userEvent.click(await screen.findByText('Spike'))

    expect(await screen.findByRole('dialog')).toHaveTextContent('Spike')
  })
})

describe('OperatorShell — a sheet is not a dead end', () => {
  it('dismisses the project sheet once a file inside it is opened', async () => {
    // The sheet covers the whole screen. Leaving it up after a pick hides the
    // very thing the pick was for, and the tap reads as a no-op.
    renderShell()
    await userEvent.click(screen.getByLabelText('Project tree'))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    act(() => {
      uiStore.openTab({ target: { type: 'view', view: 'runs' }, title: 'Runs' })
    })

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('dismisses it even when the pick is the tab already in front', async () => {
    // activeTabId does not change here, which is exactly why the shell watches
    // navSeq instead.
    act(() => {
      uiStore.openTab({ target: { type: 'view', view: 'runs' }, title: 'Runs' })
    })
    renderShell()
    await userEvent.click(screen.getByLabelText('Project tree'))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    act(() => {
      uiStore.openTab({ target: { type: 'view', view: 'runs' }, title: 'Runs' })
    })

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
