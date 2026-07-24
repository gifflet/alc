// LoopDetail.tsx — One loop: persisted state + per-cycle ledger with a CSS chart.
import { RefreshCw } from 'lucide-react'
import { useLoopLedger, useLoopState } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { EmptyState } from '../components/EmptyState'
import { Loading, Metric, Pill } from '../components/primitives'
import type { Tone } from '../components/StatusDot'
import type { CycleRecord, LoopStatus } from '../api/types'

const STATUS_TONE: Record<LoopStatus, Tone> = {
  pending: 'idle',
  running: 'running',
  stopped: 'error',
}

/** A compact CSS bar chart: succeeded (green) over failed (red) per cycle. */
function LedgerChart({ records }: { records: CycleRecord[] }) {
  const max = Math.max(1, ...records.map((r) => r.succeeded + r.failed))
  return (
    <div className="flex h-24 items-end gap-1 rounded-panel border border-border bg-base p-2">
      {records.map((r) => {
        const okH = (r.succeeded / max) * 100
        const failH = (r.failed / max) * 100
        return (
          <div
            key={r.cycle}
            title={`cycle ${r.cycle}: ${r.succeeded} ok, ${r.failed} failed`}
            className="flex min-w-[6px] flex-1 flex-col justify-end"
          >
            <div className="w-full bg-error" style={{ height: `${failH}%` }} />
            <div className="w-full bg-live" style={{ height: `${okH}%` }} />
          </div>
        )
      })}
    </div>
  )
}

function budget(used: Record<string, number>): string {
  const entries = Object.entries(used)
  if (entries.length === 0) return '—'
  return entries.map(([k, v]) => `${k}=${v}`).join(' · ')
}

export function LoopDetail({ name }: { name: string }) {
  const id = useProjectId()
  const state = useLoopState(id, name)
  const ledger = useLoopLedger(id, name)

  if (state.isLoading) return <Loading />
  if (!state.data) return <EmptyState icon={RefreshCw} message={`Could not load loop ${name}.`} />

  const s = state.data
  const records = ledger.data?.records ?? []

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <header className="flex items-center gap-3">
        <RefreshCw className="h-4 w-4 text-muted" />
        <h1 className="text-[14px] font-medium text-primary">{name}</h1>
        <Pill tone={STATUS_TONE[s.status]}>{s.status}</Pill>
        {s.stopped_reason && <span className="text-[12px] text-error">{s.stopped_reason}</span>}
      </header>

      <div className="flex gap-6 rounded-panel border border-border bg-panel px-4 py-3">
        <Metric label="cycle" value={s.cycle} />
        <Metric
          label="no progress"
          value={s.consecutive_no_progress}
          tone={s.consecutive_no_progress > 0 ? 'warn' : undefined}
        />
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[12px] text-primary">{budget(s.budget_used)}</span>
          <span className="text-[11px] uppercase tracking-wide text-faint">budget used</span>
        </div>
      </div>

      <section>
        <h2 className="mb-2 text-[11px] uppercase tracking-wide text-faint">Ledger</h2>
        {records.length === 0 ? (
          <p className="text-[12px] text-faint">This loop has not run any cycle yet.</p>
        ) : (
          <>
            <LedgerChart records={records} />
            <table className="mt-3 w-full border-collapse text-[12px]">
              <thead>
                <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-faint">
                  <th className="px-2 py-1 font-medium">Cycle</th>
                  <th className="px-2 py-1 font-medium">Replenished</th>
                  <th className="px-2 py-1 font-medium">Drained</th>
                  <th className="px-2 py-1 font-medium">Ok</th>
                  <th className="px-2 py-1 font-medium">Failed</th>
                  <th className="px-2 py-1 font-medium">Merged</th>
                  <th className="px-2 py-1 font-medium">Progress</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {records.map((r) => (
                  <tr key={r.cycle} className="h-[28px] border-b border-border/60">
                    <td className="px-2 text-muted">{r.cycle}</td>
                    <td className="px-2 text-muted">
                      <span className="flex items-center gap-2">
                        {r.replenished}
                        {r.replenish_failed && <Pill tone="warn">replenish failed</Pill>}
                      </span>
                    </td>
                    <td className="px-2 text-muted">{r.drained}</td>
                    <td className="px-2 text-live">{r.succeeded}</td>
                    <td className="px-2 text-error">{r.failed}</td>
                    <td className="px-2 text-muted">
                      {r.merged}
                      {r.left > 0 && <span className="text-warn"> / {r.left} left</span>}
                    </td>
                    <td className="px-2">
                      {r.progress ? (
                        <span className="text-live">yes</span>
                      ) : (
                        <span className="text-faint">no</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </div>
  )
}
