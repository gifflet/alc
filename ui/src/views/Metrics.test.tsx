import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Metrics } from './Metrics'
import { installFetch, renderWithProviders } from '../test/utils'
import type { MetricSeries } from '../api/types'

describe('Metrics', () => {
  it('renders a series per check, distinguishing accepted from rejected points', async () => {
    const series: MetricSeries = {
      'bundle-size': [
        { ts: 1, value: 100, run: 'ship', delta: null, trend: 'n/a', passed: true },
        { ts: 2, value: 110, run: 'ship', delta: 10, trend: 'up', passed: false },
      ],
    }
    installFetch({ '/metrics': series })
    renderWithProviders(<Metrics />)

    expect(await screen.findByText('bundle-size')).toBeInTheDocument()
    expect(screen.getByText('accepted')).toBeInTheDocument()
    expect(screen.getByText('rejected')).toBeInTheDocument()
    // The raw delta is shown, never judged good/bad.
    expect(screen.getByText('+10')).toBeInTheDocument()
  })

  it('lets the chart columns stretch, so percentage-height bars can render', async () => {
    // The bug: with `items-end` each column sized to content, the bar's height:%
    // resolved against zero, and the chart showed an empty box (found live on
    // the Metrics screen; Dashboard's ActivityChart fixed the same collapse).
    // jsdom computes no layout, so the class itself is what this guards.
    const series: MetricSeries = {
      'bundle-size': [{ ts: 1, value: 100, run: 'ship', delta: null, trend: 'n/a', passed: true }],
    }
    installFetch({ '/metrics': series })
    renderWithProviders(<Metrics />)

    const bar = await screen.findByTitle(/ship: 100/)
    const chart = bar.parentElement!
    expect(chart.className).toContain('items-stretch')
    expect(chart.className).not.toContain('items-end')
  })

  it('renders one section per check when the ledger has more than one', async () => {
    const series: MetricSeries = {
      'bundle-size': [{ ts: 1, value: 100, run: 'ship', delta: null, trend: 'n/a', passed: true }],
      'p95-latency': [{ ts: 1, value: 250, run: 'ship', delta: null, trend: 'n/a', passed: true }],
    }
    installFetch({ '/metrics': series })
    renderWithProviders(<Metrics />)

    expect(await screen.findByText('bundle-size')).toBeInTheDocument()
    expect(screen.getByText('p95-latency')).toBeInTheDocument()
  })

  it('shows an empty state that guides the operator to add a metric check', async () => {
    installFetch({ '/metrics': {} })
    renderWithProviders(<Metrics />)

    expect(await screen.findByText(/no metric measurements yet/i)).toBeInTheDocument()
    expect(screen.getByText(/grow blueprint ships a commented example/i)).toBeInTheDocument()
  })
})
