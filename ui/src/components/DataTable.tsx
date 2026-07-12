// DataTable.tsx — Compact, dense data table primitive (28px rows).
import type { ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: ReactNode
  render: (row: T) => ReactNode
  /** Extra classes for both header and cells (alignment, width, mono). */
  className?: string
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  activeKey,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
  activeKey?: string
}) {
  return (
    <table className="w-full border-collapse text-[12px]">
      <thead>
        <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-faint">
          {columns.map((c) => (
            <th key={c.key} className={`px-2 py-1 font-medium ${c.className ?? ''}`}>
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const key = rowKey(row)
          const active = key === activeKey
          // Clickable rows are reachable by keyboard and exposed as buttons.
          const clickable = Boolean(onRowClick)
          return (
            <tr
              key={key}
              role={clickable ? 'button' : undefined}
              tabIndex={clickable ? 0 : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={
                onRowClick
                  ? (e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onRowClick(row)
                      }
                    }
                  : undefined
              }
              className={`h-[28px] border-b border-border/60 transition-colors duration-120 ${
                clickable ? 'cursor-pointer' : ''
              } ${active ? 'bg-hover' : 'hover:bg-hover'}`}
            >
              {columns.map((c) => (
                <td key={c.key} className={`px-2 py-1 align-middle ${c.className ?? ''}`}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
