import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DataTable, appearanceOnly } from './DataTable'
import type { Column } from './DataTable'
import { clearMatchMedia, mockMatchMedia } from '../test/utils'

afterEach(() => clearMatchMedia())

interface Row {
  id: string
  label: string
}

const columns: Column<Row>[] = [{ key: 'label', header: 'Label', render: (r) => r.label }]

describe('DataTable a11y', () => {
  it('exposes clickable rows as keyboard-reachable buttons', () => {
    render(
      <DataTable columns={columns} rows={[{ id: 'a', label: 'Alpha' }]} rowKey={(r) => r.id} onRowClick={() => {}} />,
    )
    const row = screen.getByRole('button')
    expect(row).toHaveAttribute('tabindex', '0')
  })

  it('fires onRowClick on Enter', async () => {
    const onRowClick = vi.fn()
    render(
      <DataTable
        columns={columns}
        rows={[{ id: 'a', label: 'Alpha' }]}
        rowKey={(r) => r.id}
        onRowClick={onRowClick}
      />,
    )
    screen.getByRole('button').focus()
    await userEvent.keyboard('{Enter}')
    expect(onRowClick).toHaveBeenCalledOnce()
  })

  it('does not mark rows as buttons when they are not clickable', () => {
    render(<DataTable columns={columns} rows={[{ id: 'a', label: 'Alpha' }]} rowKey={(r) => r.id} />)
    expect(screen.queryByRole('button')).toBeNull()
  })
})

describe('DataTable DOM stability', () => {
  it('keeps the same row node across a data refetch (stable keys)', () => {
    const rows: Row[] = [
      { id: 'a', label: 'Alpha' },
      { id: 'b', label: 'Beta' },
    ]
    const { rerender } = render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />)
    const before = screen.getByText('Alpha').closest('tr')

    // A refetch returns brand-new object references with the same keys.
    const refetched = rows.map((r) => ({ ...r }))
    rerender(<DataTable columns={columns} rows={refetched} rowKey={(r) => r.id} />)

    const after = screen.getByText('Alpha').closest('tr')
    expect(after).toBe(before)
  })
})

interface WideRow {
  id: string
  name: string
  state: string
  size: string
}

/** One column of each priority, so the collapse rules are all exercised. */
const wideColumns: Column<WideRow>[] = [
  { key: 'name', header: 'Name', priority: 1, render: (r) => r.name },
  { key: 'state', header: 'State', priority: 2, render: (r) => r.state },
  { key: 'size', header: 'Size', priority: 3, render: (r) => r.size },
]

const wideRows: WideRow[] = [{ id: 'a', name: 'alpha', state: 'live', size: '2 KB' }]

describe('DataTable narrow collapse', () => {
  it('renders cards instead of a table below the breakpoint', () => {
    mockMatchMedia(['max-width: 767px'])
    const { container } = render(
      <DataTable columns={wideColumns} rows={wideRows} rowKey={(r) => r.id} />,
    )
    expect(container.querySelector('table')).toBeNull()
    expect(container.querySelector('ul')).not.toBeNull()
  })

  it('keeps priority 1 and 2 but removes priority 3 from the DOM entirely', () => {
    mockMatchMedia(['max-width: 767px'])
    render(<DataTable columns={wideColumns} rows={wideRows} rowKey={(r) => r.id} />)
    expect(screen.getByText('alpha')).toBeInTheDocument()
    expect(screen.getByText('live')).toBeInTheDocument()
    // Dropped, not merely hidden — a screen reader must not announce it.
    expect(screen.queryByText('2 KB')).toBeNull()
  })

  it('labels priority-2 fields in the card body', () => {
    mockMatchMedia(['max-width: 767px'])
    render(<DataTable columns={wideColumns} rows={wideRows} rowKey={(r) => r.id} />)
    expect(screen.getByText('State')).toBeInTheDocument()
  })

  it('activates a card row by click and by keyboard, like a table row', async () => {
    mockMatchMedia(['max-width: 767px'])
    const onRowClick = vi.fn()
    render(
      <DataTable
        columns={wideColumns}
        rows={wideRows}
        rowKey={(r) => r.id}
        onRowClick={onRowClick}
      />,
    )
    const card = screen.getByRole('button')
    await userEvent.click(card)
    expect(onRowClick).toHaveBeenCalledTimes(1)

    card.focus()
    await userEvent.keyboard('{Enter}')
    expect(onRowClick).toHaveBeenCalledTimes(2)
  })

  it('still renders the table when only a coarse pointer matches (tablet, wide)', () => {
    mockMatchMedia(['pointer: coarse'])
    const { container } = render(
      <DataTable columns={wideColumns} rows={wideRows} rowKey={(r) => r.id} />,
    )
    // Density becomes comfortable, but the grid still fits — keep the table.
    expect(container.querySelector('table')).not.toBeNull()
  })

  it('falls back to the table when the host has no matchMedia at all', () => {
    clearMatchMedia()
    const { container } = render(
      <DataTable columns={wideColumns} rows={wideRows} rowKey={(r) => r.id} />,
    )
    expect(container.querySelector('table')).not.toBeNull()
  })
})

describe('appearanceOnly', () => {
  it('drops width classes that only make sense in a table', () => {
    // Measured on device: a `w-6` status cell collapsed to 4px inside a card.
    expect(appearanceOnly('w-6')).toBe('')
    expect(appearanceOnly('w-24 font-mono text-faint')).toBe('font-mono text-faint')
    expect(appearanceOnly('min-w-0 max-w-xs text-muted')).toBe('text-muted')
  })

  it('keeps appearance classes untouched', () => {
    expect(appearanceOnly('font-mono text-primary tabular')).toBe('font-mono text-primary tabular')
  })

  it('tolerates undefined and extra whitespace', () => {
    expect(appearanceOnly(undefined)).toBe('')
    expect(appearanceOnly('  w-16   text-muted  ')).toBe('text-muted')
  })
})

describe('DataTable card identity row', () => {
  const twoIdentity: Column<WideRow>[] = [
    { key: 'dot', header: '', priority: 1, render: () => <i data-testid="dot" /> },
    { key: 'name', header: 'Name', priority: 1, render: (r) => r.name },
  ]

  it('does not let a fixed-size identity field shrink', () => {
    mockMatchMedia(['max-width: 767px'])
    const { container } = render(
      <DataTable columns={twoIdentity} rows={wideRows} rowKey={(r) => r.id} />,
    )
    const spans = container.querySelectorAll('li > div > span')
    expect(spans).toHaveLength(2)
    // First (the dot) holds its size; last takes the rest and truncates.
    expect(spans[0].className).toContain('shrink-0')
    expect(spans[0].className).not.toContain('min-w-0')
    expect(spans[1].className).toContain('truncate')
    expect(spans[1].className).toContain('min-w-0')
  })
})
