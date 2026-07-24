// Compare.tsx — Archived `alc explore` variants, side by side, with Adopt.
//
// A dedicated view (not a panel): variant rows carry enough columns (branch,
// checks, scorecard, cost, diffstat) that a side-by-side table earns its own
// screen, matching how Runs/Team/Metrics each get one rather than being
// squeezed into a Dashboard card.
import { useState } from 'react'
import { GitCompare, Sparkles } from 'lucide-react'
import { ApiError } from '../api/client'
import { useAdoptVariant, useVariants } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { ConfirmDialog } from '../components/Dialog'
import { DataTable } from '../components/DataTable'
import type { Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { Loading, Pill } from '../components/primitives'
import { formatCost } from '../lib/format'
import { ExploreDialog } from './ExploreDialog'
import type { AdoptResult, VariantRow } from '../api/types'

function apiMessage(error: unknown): string | null {
  if (error instanceof ApiError) return error.message
  return error ? 'Request failed.' : null
}

function scorecardLabel(row: VariantRow): string {
  if (!row.scorecard) return '—'
  const { span, passes, streak, touch } = row.scorecard
  return `span=${span} passes=${passes} streak=${streak} touch=${touch}`
}

function diffstatLabel(row: VariantRow): string {
  if (!row.diffstat) return '—'
  const { adds, dels, files_deleted } = row.diffstat
  const deleted = files_deleted > 0 ? ` (${files_deleted} file${files_deleted === 1 ? '' : 's'} deleted)` : ''
  return `+${adds}/-${dels}${deleted}`
}

export function Compare() {
  const id = useProjectId()
  const { data, isLoading } = useVariants(id)
  const adopt = useAdoptVariant(id)
  const [exploring, setExploring] = useState(false)
  const [adopting, setAdopting] = useState<string | null>(null)
  const [adoptResult, setAdoptResult] = useState<AdoptResult | null>(null)

  if (isLoading) return <Loading />
  const rows = data ?? []

  const confirmAdopt = () => {
    if (!adopting) return
    adopt.mutate(adopting, {
      onSuccess: (result) => {
        setAdoptResult(result)
        setAdopting(null)
      },
    })
  }

  const columns: Column<VariantRow>[] = [
    { key: 'branch', header: 'Branch', className: 'font-mono text-muted', render: (r) => r.branch ?? '—' },
    {
      key: 'engine',
      header: 'Engine / Tier',
      className: 'w-32 text-faint',
      render: (r) => `${r.engine ?? '—'}${r.tier ? ` / ${r.tier}` : ''}`,
    },
    {
      key: 'result',
      header: 'Result',
      className: 'w-16',
      render: (r) => <Pill tone={r.success ? 'live' : 'error'}>{r.success ? 'ok' : 'failed'}</Pill>,
    },
    { key: 'checks', header: 'Checks', className: 'text-muted', render: (r) => r.checks },
    { key: 'scorecard', header: 'Scorecard', className: 'tabular text-muted', render: scorecardLabel },
    {
      key: 'cost',
      header: 'Cost',
      className: 'w-16 tabular text-muted',
      render: (r) => (r.usage?.cost_usd != null ? formatCost(r.usage.cost_usd) : '—'),
    },
    { key: 'diffstat', header: 'Diffstat', className: 'font-mono text-faint', render: diffstatLabel },
    {
      key: 'actions',
      header: '',
      className: 'w-20',
      render: (r) =>
        r.branch ? (
          <button
            type="button"
            aria-label={`Adopt ${r.branch}`}
            onClick={() => setAdopting(r.branch as string)}
            disabled={adopt.isPending}
            className="rounded-panel border border-accent/60 bg-accent/10 px-2 py-0.5 text-[11px] text-accent hover:bg-accent/20 disabled:opacity-40"
          >
            Adopt
          </button>
        ) : null,
    },
  ]

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <GitCompare className="h-4 w-4 text-muted" />
          <h1 className="text-[14px] font-medium text-primary">Compare</h1>
        </div>
        <button
          type="button"
          onClick={() => setExploring(true)}
          className="flex items-center gap-1 rounded-panel border border-accent/60 bg-accent/10 px-2 py-1 text-[11px] text-accent hover:bg-accent/20"
        >
          <Sparkles className="h-3 w-3" />
          Explore
        </button>
      </header>

      {rows.length === 0 ? (
        <EmptyState icon={GitCompare} message="No archived variants yet — run Explore to compare a few." />
      ) : (
        <div className="overflow-x-auto">
          <DataTable columns={columns} rows={rows} rowKey={(r) => r.branch ?? r.checks} />
        </div>
      )}

      {adoptResult && adoptResult.conflicted.length > 0 && (
        // adopt_variant() always discards the siblings, even when the winner's own
        // cherry-pick conflicts — so this is never silent: the operator must resolve
        // the winner manually, but its (now former) siblings are already gone.
        <p className="text-[11px] text-warn">
          Left for manual resolution: {adoptResult.conflicted.join(', ')}
        </p>
      )}

      {apiMessage(adopt.error) && <p className="text-[11px] text-error">{apiMessage(adopt.error)}</p>}

      {exploring && <ExploreDialog onClose={() => setExploring(false)} />}

      {adopting && (
        <ConfirmDialog
          title="Adopt this variant?"
          message={`This integrates ${adopting} and discards its unmerged sibling variant branches. This cannot be undone.`}
          confirmLabel="Adopt"
          onConfirm={confirmAdopt}
          onCancel={() => setAdopting(null)}
        />
      )}
    </div>
  )
}
