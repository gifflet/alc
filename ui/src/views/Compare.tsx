// Compare.tsx — Archived `alc explore` variants, side by side, with Adopt.
//
// A dedicated view (not a panel): variant rows carry enough columns (branch,
// checks, scorecard, cost, diffstat) that a side-by-side table earns its own
// screen, matching how Runs/Team/Metrics each get one rather than being
// squeezed into a Dashboard card.
import { useState } from 'react'
import { GitCompare, Sparkles, X } from 'lucide-react'
import { ApiError } from '../api/client'
import { useAdoptVariant, useVariantDiff, useVariants } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { CodeView } from '../components/CodeView'
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
  // A SINGLE open diff at a time — its branch, or null when none is expanded.
  // The hook is enabled-gated on this, so the fetch is lazy (only on expand).
  const [diffBranch, setDiffBranch] = useState<string | null>(null)
  const diff = useVariantDiff(id, diffBranch)

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
    { key: 'branch', header: 'Branch', className: 'font-mono text-muted', priority: 1, render: (r) => r.branch ?? '—' },
    {
      key: 'engine',
      priority: 3,
      header: 'Engine / Tier',
      className: 'w-32 text-faint',
      render: (r) => `${r.engine ?? '—'}${r.tier ? ` / ${r.tier}` : ''}`,
    },
    {
      key: 'result',
      priority: 1,
      header: 'Result',
      className: 'w-16',
      render: (r) => <Pill tone={r.success ? 'live' : 'error'}>{r.success ? 'ok' : 'failed'}</Pill>,
    },
    { key: 'checks', header: 'Checks', className: 'text-muted', priority: 2, render: (r) => r.checks },
    { key: 'scorecard', header: 'Scorecard', className: 'tabular text-muted', priority: 2, render: scorecardLabel },
    {
      key: 'cost',
      priority: 2,
      header: 'Cost',
      className: 'w-16 tabular text-muted',
      render: (r) => (r.usage?.cost_usd != null ? formatCost(r.usage.cost_usd) : '—'),
    },
    { key: 'diffstat', header: 'Diffstat', className: 'font-mono text-faint', priority: 3, render: diffstatLabel },
    {
      key: 'actions',
      priority: 1,
      header: '',
      className: 'w-32',
      render: (r) =>
        !r.branch ? null : r.live ? (
          <div className="flex items-center justify-end gap-1.5">
            <button
              type="button"
              aria-label={`View diff of ${r.branch}`}
              aria-pressed={diffBranch === r.branch}
              // Toggling the already-open row closes it — a second click hides the panel.
              onClick={() => setDiffBranch(diffBranch === r.branch ? null : (r.branch as string))}
              className="rounded-panel border border-border px-2 py-0.5 text-[length:var(--ui-text-label)] text-muted hover:bg-panel aria-pressed:border-accent/60 aria-pressed:text-accent"
            >
              Diff
            </button>
            <button
              type="button"
              aria-label={`Adopt ${r.branch}`}
              onClick={() => setAdopting(r.branch as string)}
              disabled={adopt.isPending}
              className="rounded-panel border border-accent/60 bg-accent/10 px-2 py-0.5 text-[length:var(--ui-text-label)] text-accent hover:bg-accent/20 disabled:opacity-40"
            >
              Adopt
            </button>
          </div>
        ) : (
          // Resolved: the branch is gone (adopted or discarded), so Diff/Adopt would
          // both 404 — show a status pill instead of a broken button. The row stays
          // in the table as history, never filtered out.
          <div className="flex items-center justify-end" title="Branch gone — already adopted or discarded">
            <Pill tone="idle">resolved</Pill>
          </div>
        ),
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
          className="flex min-h-[var(--ui-control-h)] items-center gap-1 rounded-panel border border-accent/60 bg-accent/10 px-2 text-[length:var(--ui-text-label)] text-accent hover:bg-accent/20"
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

      {diffBranch && (
        // The actual change behind the summary metrics — so metric-tied variants
        // (identical checks/scorecard/cost) can still be told apart at a glance.
        <div className="rounded-panel border border-border">
          <header className="flex items-center justify-between border-b border-border px-3 py-1.5">
            <span className="font-mono text-[length:var(--ui-text-label)] text-muted">
              {diffBranch}
              {diff.data ? ` vs ${diff.data.base}` : ''}
            </span>
            <button
              type="button"
              aria-label="Close diff"
              onClick={() => setDiffBranch(null)}
              className="text-faint hover:text-muted"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </header>
          <div className="p-3">
            {diff.isLoading ? (
              <Loading />
            ) : apiMessage(diff.error) ? (
              <p className="text-[length:var(--ui-text-label)] text-error">{apiMessage(diff.error)}</p>
            ) : diff.data?.diff === '' ? (
              <p className="text-[length:var(--ui-text-label)] text-muted">No changes vs {diff.data.base}.</p>
            ) : diff.data ? (
              <div className="max-h-[50vh] overflow-auto rounded-panel border border-border">
                <CodeView code={diff.data.diff} lang="diff" />
              </div>
            ) : null}
            {diff.data?.truncated && (
              <p className="mt-2 text-[length:var(--ui-text-label)] text-warn">
                Diff truncated — run `git diff {diff.data.base}...{diffBranch}` for the full change.
              </p>
            )}
          </div>
        </div>
      )}

      {adoptResult && adoptResult.conflicted.length > 0 && (
        // adopt_variant() always discards the siblings, even when the winner's own
        // cherry-pick conflicts — so this is never silent: the operator must resolve
        // the winner manually, but its (now former) siblings are already gone.
        <p className="text-[length:var(--ui-text-label)] text-warn">
          Left for manual resolution: {adoptResult.conflicted.join(', ')}
        </p>
      )}

      {apiMessage(adopt.error) && <p className="text-[length:var(--ui-text-label)] text-error">{apiMessage(adopt.error)}</p>}

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
