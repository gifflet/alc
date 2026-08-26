// Checks.tsx — Two Maintainer reads over checks.py, surfaced in one view:
// History (per-check pass-rate/mean-duration/flake-score) and Audit (proposed
// check-set upgrades + smoke-only Blueprints). Both are read-only — the UI
// never reimplements checks.py, it only renders what the routes return.
import { ShieldCheck } from 'lucide-react'
import { useChecksAudit, useChecksHistory } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { DataTable } from '../components/DataTable'
import type { Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { Loading, Pill } from '../components/primitives'
import { OnboardPanel } from './OnboardPanel'
import type {
  CheckHistoryEntry,
  CheckProposal,
  CheckSetAudit,
  ChecksAudit,
  SmokeOnlyBlueprint,
} from '../api/types'

function formatPercent(rate: number): string {
  return `${Math.round(rate * 100)}%`
}

function formatDuration(seconds: number): string {
  return `${seconds.toFixed(2)}s`
}

/** History table: pass-rate/duration are plain numbers — only flake_score gets
 * a tone, and only the factual binary the data itself carries: it flipped at
 * least once (warn) vs it never did (idle), never a made-up threshold. */
function HistoryTable({ entries }: { entries: CheckHistoryEntry[] }) {
  const columns: Column<CheckHistoryEntry>[] = [
    { key: 'name', header: 'Check', className: 'font-mono text-primary', priority: 1, render: (h) => h.name },
    { key: 'runs', header: 'Runs', className: 'w-16 tabular text-muted', priority: 3, render: (h) => h.runs },
    {
      key: 'pass_rate',
      priority: 2,
      header: 'Pass rate',
      className: 'w-24 tabular text-muted',
      render: (h) => `${formatPercent(h.pass_rate)} (${h.passes}/${h.runs})`,
    },
    {
      key: 'mean_duration_s',
      priority: 3,
      header: 'Mean duration',
      className: 'w-28 tabular text-muted',
      render: (h) => formatDuration(h.mean_duration_s),
    },
    {
      key: 'flake_score',
      priority: 2,
      header: 'Flake score',
      className: 'w-28',
      render: (h) => (
        <Pill tone={h.flake_score > 0 ? 'warn' : 'idle'}>{h.flake_score.toFixed(2)}</Pill>
      ),
    },
  ]
  return (
    <div className="overflow-x-auto">
      <DataTable columns={columns} rows={entries} rowKey={(h) => h.name} />
    </div>
  )
}

function ProposalList({
  title,
  proposals,
  tone,
  hints,
}: {
  title: string
  proposals: CheckProposal[]
  tone: 'live' | 'warn'
  hints?: Record<string, string>
}) {
  if (proposals.length === 0) return null
  return (
    <div className="mt-1.5">
      <p className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">{title}</p>
      <ul className="mt-0.5 flex flex-col gap-0.5">
        {proposals.map(([name, command]) => (
          <li key={name} className="flex items-center gap-2 text-[length:var(--ui-text-body)]">
            <Pill tone={tone}>{name}</Pill>
            <span className="font-mono text-[length:var(--ui-text-label)] text-muted">{command.join(' ')}</span>
            {hints?.[name] && (
              <span className="text-[length:var(--ui-text-label)] text-warn">{hints[name]}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function CheckSetCard({ cs }: { cs: CheckSetAudit }) {
  return (
    <div className="rounded-panel border border-border bg-panel p-3">
      <div className="flex items-center gap-2">
        <span className="text-[length:var(--ui-text-body)] font-medium text-primary">{cs.set_name}</span>
        <Pill tone={cs.is_new ? 'accent' : 'idle'}>{cs.is_new ? 'new' : 'existing'}</Pill>
      </div>
      <ProposalList title="Available to add (binary on PATH)" proposals={cs.add} tone="live" />
      <ProposalList
        title="Unavailable (binary not on PATH)"
        proposals={cs.unavailable}
        tone="warn"
        hints={cs.install_hints}
      />
    </div>
  )
}

function SmokeOnlySection({ blueprints }: { blueprints: SmokeOnlyBlueprint[] }) {
  if (blueprints.length === 0) return null
  return (
    <div>
      <h3 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
        Smoke-only Blueprints
      </h3>
      <ul className="flex flex-col gap-1">
        {blueprints.map((b) => (
          <li key={b.blueprint} className="text-[length:var(--ui-text-body)] text-muted">
            <span className="font-mono text-primary">{b.blueprint}</span>{' '}
            {b.stacks.length === 0 ? (
              <>
                resolves to only the smoke placeholder because no stack was detected — add real
                checks to the manifest <span className="font-mono">check_sets</span> (also editable
                in the Manifest/Checks UI).
              </>
            ) : (
              <>
                resolves to only the smoke placeholder while {b.stacks.join(', ')} is detected.
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function AuditSection({ audit }: { audit: ChecksAudit }) {
  const empty = audit.check_sets.length === 0 && audit.smoke_only_blueprints.length === 0
  if (empty) {
    return (
      <p className="text-[length:var(--ui-text-body)] text-faint">
        No upgrades proposed — check_sets are current with the detected stack(s).
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      {audit.check_sets.length > 0 && (
        <div className="flex flex-col gap-2">
          {audit.check_sets.map((cs) => (
            <CheckSetCard key={cs.set_name} cs={cs} />
          ))}
        </div>
      )}
      <SmokeOnlySection blueprints={audit.smoke_only_blueprints} />
    </div>
  )
}

export function Checks() {
  const id = useProjectId()
  const history = useChecksHistory(id)
  const audit = useChecksAudit(id)

  if (history.isLoading || audit.isLoading) return <Loading />

  const entries = history.data ?? []

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <header className="flex items-center gap-3">
        <ShieldCheck className="h-4 w-4 text-muted" />
        <h1 className="text-[14px] font-medium text-primary">Checks</h1>
      </header>

      <section>
        <h2 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">History</h2>
        {entries.length === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            message="No check history yet — run `alc run`/`alc tick` to populate the run logs."
          />
        ) : (
          <HistoryTable entries={entries} />
        )}
      </section>

      <section>
        <h2 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Audit</h2>
        {audit.data && <AuditSection audit={audit.data} />}
      </section>

      <section>
        <h2 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Onboard</h2>
        <OnboardPanel />
      </section>
    </div>
  )
}
