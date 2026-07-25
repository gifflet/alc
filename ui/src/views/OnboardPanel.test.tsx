import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OnboardPanel } from './OnboardPanel'
import { installFetch, renderWithProviders } from '../test/utils'
import type { OnboardApplyResult, OnboardProposal } from '../api/types'

const emptyProposal: OnboardProposal = {
  check_sets: {},
  blueprint_opt_ins: {},
  stage: null,
  team_hints: [],
  unknowns: ['no existing check definitions found — add checks manually …'],
}

// The state a project lands in once `alc onboard` has already been adopted: the
// live "project" set is suppressed and its reason carried in `unknowns`.
const adoptedProposal: OnboardProposal = {
  check_sets: {},
  blueprint_opt_ins: {},
  stage: null,
  team_hints: [],
  unknowns: [
    "the 'project' check_set already exists — its checks are live; edit the manifest to change them",
  ],
}

const populatedProposal: OnboardProposal = {
  check_sets: {
    project: [
      {
        name: 'test',
        command: ['make', 'test'],
        shell: null,
        available: true,
        origin: 'harvest',
        source_path: 'Makefile',
      },
      {
        name: 'lint',
        command: ['make', 'lint'],
        shell: null,
        available: false,
        origin: 'harvest',
        source_path: 'Makefile',
      },
    ],
  },
  blueprint_opt_ins: { chore: 'project', bug: 'project' },
  stage: null,
  team_hints: [],
  unknowns: [],
}

const applyResult: OnboardApplyResult = {
  applied: true,
  sets_added: ['project'],
  blueprints_opted_in: ['chore', 'bug'],
  stage_set: false,
  notes: [],
}

describe('OnboardPanel', () => {
  it('surfaces the empty-harvest reason and points at the CLI --assist path', async () => {
    installFetch({ '/checks/onboard': emptyProposal })
    renderWithProviders(<OnboardPanel />)

    // The proposal's own reason is shown — not a hard-coded claim.
    expect(
      await screen.findByText(/no existing check definitions found/i),
    ).toBeInTheDocument()
    expect(screen.getByText('alc onboard --assist')).toBeInTheDocument()
    // The empty state never invents an Adopt action.
    expect(screen.queryByRole('button', { name: 'Adopt' })).not.toBeInTheDocument()
  })

  it('surfaces the already-onboarded reason instead of the empty-harvest claim', async () => {
    installFetch({ '/checks/onboard': adoptedProposal })
    renderWithProviders(<OnboardPanel />)

    // Once adopted, the honest reason is "already exists", never "none harvested".
    expect(
      await screen.findByText(/the 'project' check_set already exists/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/no existing check definitions found/i)).not.toBeInTheDocument()
    // Still the CLI hint, still no invented Adopt action.
    expect(screen.getByText('alc onboard --assist')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Adopt' })).not.toBeInTheDocument()
  })

  it('renders the proposed project check_set, opt-ins and an Adopt button', async () => {
    installFetch({ '/checks/onboard': populatedProposal })
    renderWithProviders(<OnboardPanel />)

    expect(await screen.findByText('test')).toBeInTheDocument()
    expect(screen.getByText('make test')).toBeInTheDocument()
    expect(screen.getByText('available')).toBeInTheDocument()
    // An off-PATH binary is flagged, never silently trusted.
    expect(screen.getByText(/commented — binary off PATH/i)).toBeInTheDocument()
    // The opt-in note names the smoke-only blueprints that gain the check_set.
    expect(screen.getByText(/will insert/i)).toBeInTheDocument()
    expect(screen.getByText('chore')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Adopt' })).toBeInTheDocument()
  })

  it('adopts the proposal via the apply endpoint and shows a summary', async () => {
    // Apply must be listed first: it is the more specific URL, and installFetch
    // matches by substring (first match wins), so the GET proposal route must
    // not shadow the POST apply route.
    const mock = installFetch({
      '/checks/onboard/apply': applyResult,
      '/checks/onboard': populatedProposal,
    })
    renderWithProviders(<OnboardPanel />)

    await userEvent.click(await screen.findByRole('button', { name: 'Adopt' }))

    const post = mock.calls.find(
      (c) => c.method === 'POST' && c.url.includes('/checks/onboard/apply'),
    )
    expect(post).toBeDefined()
    // No stage was chosen, so the body carries an explicit null.
    expect(post?.body).toEqual({ stage: null })

    expect(await screen.findByText(/adopted/i)).toBeInTheDocument()
  })
})
