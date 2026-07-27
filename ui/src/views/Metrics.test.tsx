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
