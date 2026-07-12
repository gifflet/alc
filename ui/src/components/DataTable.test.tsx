import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DataTable } from './DataTable'
import type { Column } from './DataTable'

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
