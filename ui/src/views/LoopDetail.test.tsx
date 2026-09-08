import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { LoopDetail } from './LoopDetail'
import { installFetch, renderWithProviders } from '../test/utils'
import type { CycleRecord, LoopState } from '../api/types'

const state: LoopState = {
  name: 'sweep',
  status: 'running',
  cycle: 2,
  consecutive_no_progress: 0,
  budget_used: {},
  stopped_reason: null,
  definition: null,
}

const okRecord: CycleRecord = {
  cycle: 1,
  replenished: 1,
  drained: 1,
  succeeded: 1,
  failed: 0,
  merged: 0,
  left: 0,
  replenish_failed: false,
  progress: true,
  budget_delta: {},
  stopped_reason: null,
}

describe('LoopDetail', () => {
  it('marks a cycle whose replenish failed in the ledger', async () => {
    const failedRecord: CycleRecord = { ...okRecord, cycle: 2, replenish_failed: true }
    installFetch({
      '/loops/sweep/state': state,
      '/loops/sweep/ledger': { records: [okRecord, failedRecord] },
    })
    renderWithProviders(<LoopDetail name="sweep" />)

    expect(await screen.findByText('replenish failed')).toBeInTheDocument()
  })

  it('does not show the marker for a normal ledger', async () => {
    installFetch({
      '/loops/sweep/state': state,
      '/loops/sweep/ledger': { records: [okRecord] },
    })
    renderWithProviders(<LoopDetail name="sweep" />)

    await screen.findByText('sweep')
    expect(screen.queryByText('replenish failed')).not.toBeInTheDocument()
  })

  it('lets the ledger chart columns stretch, so percentage-height bars can render', async () => {
    // The bug: with `items-end` each column sized to content, the bars' height:%
    // resolved against zero, and the chart showed an empty box (Dashboard's
    // ActivityChart fixed the same collapse). jsdom computes no layout, so the
    // class itself is what this guards.
    installFetch({
      '/loops/sweep/state': state,
      '/loops/sweep/ledger': { records: [okRecord] },
    })
    renderWithProviders(<LoopDetail name="sweep" />)

    const bar = await screen.findByTitle(/cycle 1: 1 ok, 0 failed/)
    const chart = bar.parentElement!
    expect(chart.className).toContain('items-stretch')
    expect(chart.className).not.toContain('items-end')
  })
})
