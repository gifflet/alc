// Dashboard.tsx — Project overview: scorecard, queue, recent runs, loops, engines.
// Every card is backed by a live query invalidated over WS — no manual refresh.
import { useState } from 'react'
import { Activity, ClipboardList, Cpu, Gauge, ListTodo, PieChart, RefreshCw } from 'lucide-react'
import {
  useAudit,
  useCollection,
  useEngines,
  useLoopState,
  useQueue,
  useRuns,
  useScorecard,
  useTeam,
} from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { openView } from '../components/ActivityBar'
import { uiStore } from '../app/uiStore'
import { formatCost } from '../lib/format'
import { formatNetLines, scorecardHistory } from '../lib/scorecard'
import type { ScorecardPoint } from '../lib/scorecard'
import { Card, Metric, Pill } from '../components/primitives'
import { EmptyState } from '../components/EmptyState'
import { RelativeTime } from '../components/RelativeTime'
import { StatusDot } from '../components/StatusDot'
import type { MixHealth } from '../api/types'

/** Per-report span bars, coloured by success — a compact trend under the totals. */
function ScorecardHistory({ points }: { points: ScorecardPoint[] }) {
  const max = Math.max(1, ...points.map((p) => p.span))
  return (
    <div className="mt-3 flex h-12 items-end gap-1 rounded-panel border border-border bg-base p-2">
      {points.map((p) => (
        <div
          key={p.stem}
          title={`${p.stem}: span=${p.span} · ${p.success ? 'ok' : 'failed'}`}
          className="flex min-w-[4px] flex-1 flex-col justify-end"
        >
          <div
            className={p.success ? 'w-full bg-live' : 'w-full bg-error'}
            style={{ height: `${Math.max(6, (p.span / max) * 100)}%` }}
          />
        </div>
      ))}
    </div>
  )
}

function ScorecardCard() {
  const id = useProjectId()
  const { data } = useScorecard(id)
  const { data: queue } = useQueue(id)
  const s = data
  const history = scorecardHistory(queue?.done ?? [])
  const netLines = formatNetLines(s?.net_lines_total)
  const warnings = s?.runs_with_warnings ?? 0
  return (
    <Card title="Scorecard" icon={Gauge}>
      {s && s.reports > 0 ? (
        <>
          <div className="grid grid-cols-4 gap-3">
            <Metric label="span" value={s.span_total} tone="live" />
            <Metric label="passes" value={s.passes_total} />
            <Metric label="streak" value={s.streak_total} />
            <Metric label="touch" value={s.touch_total} tone={s.touch_total > 0 ? 'error' : undefined} />
            <Metric label="reports" value={s.reports} />
            <Metric label="ok" value={s.successes} tone="live" />
            <Metric label="failed" value={s.failures} tone={s.failures > 0 ? 'error' : undefined} />
            <Metric
              label="net lines"
              value={netLines ?? '—'}
              tone={s.net_lines_total != null && s.net_lines_total < 0 ? 'live' : undefined}
            />
          </div>
          {warnings > 0 && (
            <div className="mt-2">
              <Pill tone="warn">
                {warnings} run{warnings === 1 ? '' : 's'} with warnings
              </Pill>
            </div>
          )}
          {history.length > 0 && <ScorecardHistory points={history} />}
        </>
      ) : (
        <p className="text-[12px] text-faint">No archived reports yet.</p>
      )}
    </Card>
  )
}

function QueueCard() {
  const id = useProjectId()
  const { data } = useQueue(id)
  const pending = data?.pending.length ?? 0
  const done = data?.done.length ?? 0
  return (
    <Card title="Queue" icon={ListTodo} action={<LinkButton onClick={() => openView('queue')} />}>
      <div className="grid grid-cols-2 gap-3">
        <Metric label="pending" value={pending} tone={pending > 0 ? 'running' : undefined} />
        <Metric label="done" value={done} />
      </div>
    </Card>
  )
}

function LinkButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-[11px] text-accent transition-colors duration-120 hover:underline"
    >
      open
    </button>
  )
}

function RunsCard() {
  const id = useProjectId()
  const { data } = useRuns(id)
  const runs = (data?.runs ?? []).slice(0, 6)
  return (
    <Card title="Recent runs" icon={Activity} action={<LinkButton onClick={() => openView('runs')} />}>
      {runs.length === 0 ? (
        <p className="text-[12px] text-faint">No runs recorded.</p>
      ) : (
        <ul className="flex flex-col">
          {runs.map((r) => (
            <li key={r.stem}>
              <button
                type="button"
                onClick={() => uiStore.openTab({ target: { type: 'run', stem: r.stem }, title: r.stem })}
                className="flex h-[26px] w-full items-center gap-2 text-left text-[12px] transition-colors duration-120 hover:bg-hover"
              >
                <StatusDot tone={r.finished ? 'idle' : 'running'} pulse={!r.finished} />
                <span className="w-10 font-mono text-[11px] text-faint">{r.kind}</span>
                <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted">{r.stem}</span>
                <RelativeTime value={r.mtime} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function LoopRow({ name }: { name: string }) {
  const id = useProjectId()
  const { data } = useLoopState(id, name)
  const tone = data?.status === 'running' ? 'running' : data?.status === 'stopped' ? 'error' : 'idle'
  return (
    <button
      type="button"
      onClick={() => uiStore.openTab({ target: { type: 'loop', name }, title: name })}
      className="flex h-[26px] w-full items-center gap-2 text-left text-[12px] transition-colors duration-120 hover:bg-hover"
    >
      <StatusDot tone={tone} pulse={data?.status === 'running'} />
      <span className="min-w-0 flex-1 truncate text-muted">{name}</span>
      <span className="tabular text-[11px] text-faint">cycle {data?.cycle ?? 0}</span>
    </button>
  )
}

function LoopsCard() {
  const id = useProjectId()
  const { data } = useCollection(id, 'loops')
  const loops = data ?? []
  return (
    <Card title="Loops" icon={RefreshCw} action={<LinkButton onClick={() => openView('loops')} />}>
      {loops.length === 0 ? (
        <p className="text-[12px] text-faint">No loops defined.</p>
      ) : (
        <div className="flex flex-col">
          {loops.map((l) => (
            <LoopRow key={l.name} name={l.name} />
          ))}
        </div>
      )}
    </Card>
  )
}

function EnginesCard() {
  const id = useProjectId()
  const { data } = useEngines(id)
  const engines = data ?? []
  return (
    <Card title="Engines" icon={Cpu}>
      <div className="flex flex-col gap-1.5">
        {engines.map((e) => (
          <div key={e.name} className="flex items-center gap-2 text-[12px]">
            <StatusDot tone={e.healthy ? 'live' : 'error'} />
            <span className="text-primary">{e.name}</span>
            {e.default && <Pill tone="accent">default</Pill>}
            <span className="ml-auto font-mono text-[11px] text-faint">{e.type}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}

/** Sum each archived run's archetype into core/secondary/off-mix run counts
 * against the stage's target mix. A null archetype is never singled out as
 * off-mix (matches stagepolicy.validate_stage_mix's "never penalised" rule). */
function mixAlignment(health: MixHealth): { core: number; secondary: number; offMix: number } {
  let core = 0
  let secondary = 0
  let offMix = 0
  for (const s of health.by_archetype) {
    if (s.archetype === null) continue
    if (health.core.includes(s.archetype)) core += s.runs
    else if (health.secondary.includes(s.archetype)) secondary += s.runs
    else offMix += s.runs
  }
  return { core, secondary, offMix }
}

function MixHealthCard() {
  const id = useProjectId()
  const { data } = useTeam(id)
  const health = data?.mix_health

  return (
    <Card title="Mix Health" icon={PieChart} action={<LinkButton onClick={() => openView('team')} />}>
      {!health || health.total_runs === 0 ? (
        <p className="text-[12px] text-faint">No data yet — no archived runs.</p>
      ) : !health.stage ? (
        <p className="text-[12px] text-faint">
          No stage declared — {health.total_runs} run{health.total_runs === 1 ? '' : 's'} unjudged.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-[12px] text-muted">
            Stage: <span className="text-primary">{health.stage}</span>
          </p>
          {(() => {
            const { core, secondary, offMix } = mixAlignment(health)
            return (
              <div className="grid grid-cols-3 gap-3">
                <Metric label="core" value={core} tone="live" />
                <Metric label="secondary" value={secondary} />
                <Metric label="off-mix" value={offMix} tone={offMix > 0 ? 'error' : undefined} />
              </div>
            )
          })()}
        </div>
      )}
    </Card>
  )
}

const AUDIT_WINDOWS = ['7d', '24h', '30m'] as const
type AuditWindowOption = (typeof AUDIT_WINDOWS)[number]

/** Aggregate archived tasks over a trailing window; the selector refetches
 * with the new `since` (each window caches separately, see keys.auditWindow). */
function AuditCard() {
  const id = useProjectId()
  const [since, setSince] = useState<AuditWindowOption>('7d')
  const { data } = useAudit(id, since)

  return (
    <Card
      title="Audit"
      icon={ClipboardList}
      action={
        <select
          aria-label="Audit window"
          value={since}
          onChange={(e) => setSince(e.target.value as AuditWindowOption)}
          className="rounded-panel border border-border bg-base px-1.5 py-0.5 text-[11px] text-primary outline-none focus:border-accent"
        >
          {AUDIT_WINDOWS.map((w) => (
            <option key={w} value={w}>
              {w}
            </option>
          ))}
        </select>
      }
    >
      {data && data.tasks_total > 0 ? (
        <div className="grid grid-cols-4 gap-3">
          <Metric label="tasks" value={data.tasks_total} />
          <Metric label="ok" value={data.tasks_ok} tone="live" />
          <Metric
            label="failed"
            value={data.tasks_failed}
            tone={data.tasks_failed > 0 ? 'error' : undefined}
          />
          <Metric label="cost" value={formatCost(data.cost_usd_total)} />
        </div>
      ) : (
        <p className="text-[12px] text-faint">No archived tasks in this window.</p>
      )}
    </Card>
  )
}

export function Dashboard() {
  const id = useProjectId()
  const { data: engines } = useEngines(id)
  if (engines === undefined) {
    // First paint before any data: keep it calm rather than a blank grid.
    return <EmptyState icon={Gauge} message="Loading project overview…" />
  }
  return (
    <div className="grid h-full grid-cols-1 content-start gap-3 overflow-auto p-4 md:grid-cols-2 xl:grid-cols-3">
      <ScorecardCard />
      <QueueCard />
      <EnginesCard />
      <RunsCard />
      <LoopsCard />
      <MixHealthCard />
      <AuditCard />
    </div>
  )
}
