// DataTable.tsx — Dense data table that collapses to cards on narrow screens.
//
// Wide: the original 28px-row table, unchanged.
// Narrow: one card per row, because a 6-column table on a 411px phone degrades
// to two visible columns behind a horizontal scrollbar (measured on device).
//
// Columns declare a priority so each view decides what survives the collapse:
//   1 = card header line (identity — always visible)
//   2 = card body, as labelled pairs
//   3 = dropped entirely when narrow (removed from the DOM, not hidden, so
//       screen readers do not announce data the operator cannot see)
import type { ReactNode } from 'react'
import { useNarrow } from '../app/useDensity'

/** 1 = identity, 2 = detail, 3 = desktop-only. Defaults to 2. */
export type ColumnPriority = 1 | 2 | 3

export interface Column<T> {
  key: string
  header: ReactNode
  render: (row: T) => ReactNode
  /** Extra classes for both header and cells (alignment, width, mono). */
  className?: string
  priority?: ColumnPriority
  /** Label for the collapsed card; falls back to `header` when it is a string. */
  cardLabel?: string
}

function priorityOf<T>(column: Column<T>): ColumnPriority {
  return column.priority ?? 2
}

/**
 * Strip column-width classes for the card layout.
 *
 * `className` carries both appearance (mono, colour, alignment) and table
 * geometry (`w-6`, `w-24`, …). The geometry is meaningless once the row is a
 * card and actively harmful: on a 411px device a `w-6` status cell was measured
 * collapsing to 4px, clipping its dot. Appearance is kept, width is dropped.
 */
export function appearanceOnly(className: string | undefined): string {
  if (!className) return ''
  return className
    .split(/\s+/)
    .filter((token) => token && !/^(min-|max-)?w-/.test(token))
    .join(' ')
}

function labelOf<T>(column: Column<T>): string {
  if (column.cardLabel !== undefined) return column.cardLabel
  return typeof column.header === 'string' ? column.header : ''
}

interface RowProps<T> {
  row: T
  active: boolean
  onRowClick?: (row: T) => void
}

/** Shared activation: a clickable row is a button by role, mouse and keyboard. */
function activation<T>({ row, onRowClick }: RowProps<T>) {
  if (!onRowClick) return {}
  return {
    role: 'button' as const,
    tabIndex: 0,
    onClick: () => onRowClick(row),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onRowClick(row)
      }
    },
  }
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
  const narrow = useNarrow()

  if (narrow) {
    const identity = columns.filter((c) => priorityOf(c) === 1)
    const detail = columns.filter((c) => priorityOf(c) === 2)
    return (
      <ul className="flex flex-col p-[var(--ui-pad-y)]">
        {rows.map((row) => {
          const key = rowKey(row)
          const active = key === activeKey
          return (
            <li
              key={key}
              {...activation({ row, active, onRowClick })}
              className={`mb-2 flex flex-col gap-[var(--ui-gap)] rounded-[var(--radius-md)] bg-raised px-[var(--ui-pad-x)] py-[var(--ui-pad-y)] text-[length:var(--ui-text-body)] shadow-[var(--elev-1)] ring-1 ring-border/40 ${
                onRowClick ? 'cursor-pointer' : ''
              } ${active ? 'bg-hover' : ''}`}
            >
              <div className="flex min-h-[var(--ui-control-h)] items-center gap-2">
                {identity.map((c, i) => {
                  // Only the last identity field may shrink and truncate: it is
                  // the long one (a name/stem). Giving `min-w-0` to the others
                  // collapses fixed-size content — measured on device, a status
                  // dot rendered at 4px of its 8px.
                  const last = i === identity.length - 1
                  return (
                    <span
                      key={c.key}
                      className={`${last ? 'min-w-0 flex-1 truncate' : 'shrink-0'} ${appearanceOnly(c.className)}`}
                    >
                      {c.render(row)}
                    </span>
                  )
                })}
              </div>
              {detail.length > 0 && (
                <dl className="grid grid-cols-2 gap-x-[var(--ui-gap)] gap-y-1">
                  {detail.map((c) => (
                    <div key={c.key} className="flex min-w-0 flex-col">
                      <dt className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
                        {labelOf(c)}
                      </dt>
                      <dd className={`min-w-0 truncate ${appearanceOnly(c.className)}`}>
                        {c.render(row)}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          )
        })}
      </ul>
    )
  }

  return (
    <table className="w-full border-collapse text-[length:var(--ui-text-body)]">
      <thead>
        <tr className="border-b border-border/50 text-left text-[length:var(--ui-text-label)] font-medium uppercase tracking-[0.06em] text-faint">
          {columns.map((c) => (
            <th
              key={c.key}
              className={`px-[var(--ui-pad-x)] py-[var(--ui-pad-y)] font-medium ${c.className ?? ''}`}
            >
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const key = rowKey(row)
          const active = key === activeKey
          const clickable = Boolean(onRowClick)
          return (
            <tr
              key={key}
              {...activation({ row, active, onRowClick })}
              // No per-row rule: a line under every row is what made the grid
              // read as a spreadsheet. Row height plus hover carries it.
              // min-h, not h: a cell may hold two lines (a run's task above its
              // stem) and a fixed height crushes them together.
              className={`min-h-[var(--ui-row-h)] transition-colors duration-120 ${
                clickable ? 'cursor-pointer' : ''
              } ${active ? 'bg-hover' : 'hover:bg-hover'}`}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`px-[var(--ui-pad-x)] py-[var(--ui-pad-y)] align-middle ${c.className ?? ''}`}
                >
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
