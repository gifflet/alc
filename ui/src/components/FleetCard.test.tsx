import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { cardState, FleetCard } from './FleetCard'
import type { FleetUnit } from '../api/types'

function unit(events: Record<string, unknown>[], overrides: Partial<FleetUnit> = {}): FleetUnit {
  return {
    stem: '20260825T100000-run-chore-tidy-aaa',
    kind: 'run',
    mtime: Date.now() / 1000,
    truncated: false,
    events: events as FleetUnit['events'],
    ...overrides,
  }
}

const STARTED = { ts: 't', event: 'mandate_started', blueprint: 'chore', task: 'tidy the imports', engine: 'mock', model: 'm' }

describe('cardState', () => {
  it('reports Act while the first turn is running', () => {
    const s = cardState(unit([STARTED, { ts: 't', event: 'act_started', attempt: 0 }]))
    expect(s.phase).toBe('act')
    expect(s.attempt).toBe(1) // attempt 0 reads as "attempt 1" to an operator
    expect(s.unit).toBe('chore')
    expect(s.task).toBe('tidy the imports')
  })

  it('reports Verify once the checks start', () => {
    const s = cardState(
      unit([
        STARTED,
        { ts: 't', event: 'act_started', attempt: 0 },
        { ts: 't', event: 'act_finished', attempt: 0, ok: true },
        { ts: 't', event: 'verify_started', attempt: 0, checks: ['build'] },
      ]),
    )
    expect(s.phase).toBe('verify')
  })

  it('reports Repair on a second Act turn', () => {
    const s = cardState(
      unit([
        STARTED,
        { ts: 't', event: 'act_started', attempt: 0 },
        { ts: 't', event: 'verify_started', attempt: 0, checks: ['build'] },
        { ts: 't', event: 'check_finished', attempt: 0, name: 'build', passed: false },
        { ts: 't', event: 'act_started', attempt: 1 },
      ]),
    )
    expect(s.phase).toBe('repair')
    expect(s.attempt).toBe(2)
  })

  it('names the check currently executing, and clears it once it finishes', () => {
    const running = cardState(
      unit([
        STARTED,
        { ts: 't', event: 'verify_started', attempt: 0, checks: ['build'] },
        { ts: 't', event: 'check_started', attempt: 0, name: 'pytest' },
      ]),
    )
    expect(running.runningCheck).toBe('pytest')

    const done = cardState(
      unit([
        STARTED,
        { ts: 't', event: 'verify_started', attempt: 0, checks: ['build'] },
        { ts: 't', event: 'check_started', attempt: 0, name: 'pytest' },
        { ts: 't', event: 'check_finished', attempt: 0, name: 'pytest', passed: true },
      ]),
    )
    expect(done.runningCheck).toBeNull()
  })

  it('reports Finished on a terminal event', () => {
    const s = cardState(
      unit([STARTED, { ts: 't', event: 'mandate_finished', success: true, attempts: 1 }]),
    )
    expect(s.phase).toBe('done')
  })

  it('falls back to the stem when the stream carries no title yet', () => {
    const s = cardState(unit([{ ts: 't', event: 'act_started', attempt: 0 }]))
    expect(s.title).toContain('20260825T100000')
  })
})

describe('FleetCard', () => {
  it('shows phase, attempt and the running check', () => {
    render(
      <FleetCard
        unit={unit([
          STARTED,
          { ts: 't', event: 'verify_started', attempt: 0, checks: ['build'] },
          { ts: 't', event: 'check_started', attempt: 0, name: 'pytest' },
        ])}
        onOpen={() => {}}
      />,
    )
    expect(screen.getByText(/Verify · attempt 1/)).toBeInTheDocument()
    expect(screen.getByText('pytest')).toBeInTheDocument()
  })

  it('discloses a truncated log instead of pretending it is complete', () => {
    render(<FleetCard unit={unit([STARTED], { truncated: true })} onOpen={() => {}} />)
    expect(screen.getByText(/log truncated/)).toBeInTheDocument()
  })
})
