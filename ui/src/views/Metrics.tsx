// Metrics.tsx — Per-project metric checks: each one's value series drawn as a
// CSS bar chart (LoopDetail's pattern — no charting lib).
//
// accepted/rejected (MetricPoint.passed) is the ONLY judgment shown on a
// point. trend/delta are the raw numeric movement and are rendered neutrally
// — never colored as good/bad. The backend deliberately does not persist
// `direction` in the ledger (a check name does not map to exactly one
// Blueprint), so the UI must not guess it either.
import { LineChart } from 'lucide-react'
import { useMetrics } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { EmptyState } from '../components/EmptyState'
import { Loading, Pill } from '../components/primitives'
import { RelativeTime } from '../components/RelativeTime'
import type { MetricPoint } from '../api/types'

const TREND_GLYPH: Record<MetricPoint['trend'], string> = {
  up: '↑',
  down: '↓',
  flat: '→',
  'n/a': '–',
}

function formatDelta(delta: number | null): string {
  if (delta === null) return '—'
  return delta > 0 ? `+${delta}` : `${delta}`
}

/** A compact CSS bar chart: one bar per point, accepted (green) vs rejected
 * (red) — mirrors LoopDetail's LedgerChart. */
function MetricChart({ points }: { points: MetricPoint[] }) {
  const max = Math.max(1, ...points.map((p) => Math.abs(p.value)))
  return (
    <div className="flex h-24 items-end gap-1 rounded-panel border border-border bg-base p-2">
      {points.map((p, i) => {
        const h = Math.max(4, (Math.abs(p.value) / max) * 100)
        return (
          <div
            key={`${p.ts}-${i}`}
            title={`${p.run}: ${p.value} (${TREND_GLYPH[p.trend]}${formatDelta(p.delta)}) — ${
              p.passed ? 'accepted' : 'rejected'
            }`}
            className="flex min-w-[6px] flex-1 flex-col justify-end"
          >
            <div
              className={p.passed ? 'w-full bg-live' : 'w-full bg-error'}
              style={{ height: `${h}%` }}
            />
          </div>
        )
      })}
    </div>
  )
}

function MetricSection({ check, points }: { check: string; points: MetricPoint[] }) {
  return (
    <section>
      <h2 className="mb-2 text-[11px] uppercase tracking-wide text-faint">{check}</h2>
      <MetricChart points={points} />
      <table className="mt-3 w-full border-collapse text-[12px]">
        <thead>
          <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-faint">
            <th className="px-2 py-1 font-medium">When</th>
            <th className="px-2 py-1 font-medium">Run</th>
            <th className="px-2 py-1 font-medium">Value</th>
            <th className="px-2 py-1 font-medium">Delta</th>
            <th className="px-2 py-1 font-medium">Trend</th>
            <th className="px-2 py-1 font-medium">Status</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {points.map((p, i) => (
            <tr key={`${p.ts}-${i}`} className="h-[28px] border-b border-border/60">
              <td className="px-2 text-muted">
                <RelativeTime value={p.ts} />
              </td>
              <td className="px-2 truncate font-mono text-[11px] text-muted">{p.run}</td>
              <td className="px-2 text-primary">{p.value}</td>
              <td className="px-2 text-muted">{formatDelta(p.delta)}</td>
              <td className="px-2 text-faint">{TREND_GLYPH[p.trend]}</td>
              <td className="px-2">
                <Pill tone={p.passed ? 'live' : 'error'}>{p.passed ? 'accepted' : 'rejected'}</Pill>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export function Metrics() {
  const id = useProjectId()
  const { data, isLoading } = useMetrics(id)

  if (isLoading) return <Loading />

  const checks = Object.entries(data ?? {})

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <header className="flex items-center gap-3">
        <LineChart className="h-4 w-4 text-muted" />
        <h1 className="text-[14px] font-medium text-primary">Metrics</h1>
      </header>

      {checks.length === 0 ? (
        <EmptyState
          icon={LineChart}
          message="No metric measurements yet — add a metric check (direction + tolerance_pct) to a Blueprint to start tracking regressions. The grow Blueprint ships a commented example."
        />
      ) : (
        checks.map(([check, points]) => <MetricSection key={check} check={check} points={points} />)
      )}
    </div>
  )
}
