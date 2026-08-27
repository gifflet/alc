// Dashboard.tsx — The project's health panel.
//
// Deliberately NOT an index of the other views: Queue and Loops cards were cut
// because the Queue, Loops and Inbox screens answer those questions with more
// detail and an action attached. What remains is what only this screen answers —
// the Scorecard trend, engine health, team mix and the cron schedule — plus
// Recent runs, kept as the one shortcut worth having (it is what lets Runs leave
// the mobile bar). Every card is a live query invalidated over WS.
import { useState } from 'react'
import { Activity, CalendarClock, ClipboardList, Cpu, Gauge, PieChart } from 'lucide-react'
import {
  useAudit,
  useEngines,
  useQueue,
  useRuns,
  useSchedule,
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
import { StartWork } from '../components/StartWork'
import { EmptyState } from '../components/EmptyState'
import { RelativeTime } from '../components/RelativeTime'
import { StatusDot } from '../components/StatusDot'
import type { MixHealth } from '../api/types'

/** Per-report span bars, coloured by success — a compact trend under the totals. */
function ScorecardHistory({ points }: { points: ScorecardPoint[] }) {
  const max = Math.max(1, ...points.map((p) => p.span))
  return (
    // items-stretch, not items-end: with `items-end` each column sizes to its
    // content, so the bar's percentage height resolved against a zero-height
    // parent and NOTHING rendered — the card showed an empty box. The column
    // stretches; `justify-end` inside it still anchors the bar to the bottom.
    <div className="mt-3 flex h-12 items-stretch gap-1 rounded-panel border border-border bg-base p-2">
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
        <p className="text-[length:var(--ui-text-body)] text-faint">No archived reports yet.</p>
      )}
    </Card>
  )
}

function LinkButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-[length:var(--ui-text-label)] text-accent transition-colors duration-120 hover:underline"
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
        <p className="text-[length:var(--ui-text-body)] text-faint">No runs recorded.</p>
      ) : (
        <ul className="flex flex-col">
          {runs.map((r) => (
            <li key={r.stem}>
              <button
                type="button"
                onClick={() => uiStore.openTab({ target: { type: 'run', stem: r.stem }, title: r.stem })}
                className="flex h-[26px] w-full items-center gap-2 text-left text-[length:var(--ui-text-body)] transition-colors duration-120 hover:bg-hover"
              >
                <StatusDot tone={r.finished ? 'idle' : 'running'} pulse={!r.finished} />
                <span className="w-10 font-mono text-[length:var(--ui-text-label)] text-faint">{r.kind}</span>
                <span className="min-w-0 flex-1 truncate font-mono text-[length:var(--ui-text-label)] text-muted">{r.stem}</span>
                <RelativeTime value={r.mtime} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function EnginesCard() {
  const id = useProjectId()
  const { data } = useEngines(id)
  const engines = data ?? []
  const mockIsDefault = engines.some((e) => e.default && e.type === 'mock')
  return (
    <Card title="Engines" icon={Cpu}>
      <div className="flex flex-col gap-1.5">
        {engines.map((e) => (
          <div key={e.name} className="flex items-center gap-2 text-[length:var(--ui-text-body)]">
            <StatusDot tone={e.healthy ? 'live' : 'error'} />
            <span className="text-primary">{e.name}</span>
            {e.default && <Pill tone="accent">default</Pill>}
            <span className="ml-auto font-mono text-[length:var(--ui-text-label)] text-faint">{e.type}</span>
          </div>
        ))}
        {mockIsDefault && (
          <p className="text-[length:var(--ui-text-label)] text-warn">
            mock is a no-op engine — runs verify nothing. Set a real default (claude-code or
            gemini) in the Manifest.
          </p>
        )}
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
        <p className="text-[length:var(--ui-text-body)] text-faint">No data yet — no archived runs.</p>
      ) : !health.stage ? (
        <p className="text-[length:var(--ui-text-body)] text-faint">
          No stage declared — {health.total_runs} run{health.total_runs === 1 ? '' : 's'} unjudged.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-[length:var(--ui-text-body)] text-muted">
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
          className="rounded-panel border border-border bg-base px-1.5 py-0.5 text-[length:var(--ui-text-label)] text-primary outline-none focus:border-accent"
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
        <p className="text-[length:var(--ui-text-body)] text-faint">No archived tasks in this window.</p>
      )}
    </Card>
  )
}

/** Read-only view of the host crontab's ALC-scheduled entries (ui-phase-5.md
 * T12). Installing/removing a schedule stays a CLI-only operation — the card
 * only ever reads, never offers a mutating control. */
function ScheduleCard() {
  const { data } = useSchedule()
  const entries = data?.entries ?? []
  return (
    <Card title="Schedule" icon={CalendarClock}>
      {!data || !data.available ? (
        <p className="text-[length:var(--ui-text-body)] text-faint">No crontab on this host.</p>
      ) : entries.length === 0 ? (
        <p className="text-[length:var(--ui-text-body)] text-faint">No ALC-scheduled entries.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {entries.map((line) => (
            <li key={line} title={line} className="truncate font-mono text-[length:var(--ui-text-label)] text-muted">
              {line}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[length:var(--ui-text-label)] text-faint">
        Read-only — install or remove a schedule with <code className="font-mono">alc schedule</code> on
        the CLI.
      </p>
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
      {/* First thing on the page, spanning the grid. Every panel below reports
          on work that already happened; this is the only one that starts any,
          and on a fresh project the rest are empty. */}
      <div className="md:col-span-2 xl:col-span-3">
        <StartWork />
      </div>
      <ScorecardCard />
      <EnginesCard />
      <RunsCard />
      <MixHealthCard />
      <AuditCard />
      <ScheduleCard />
    </div>
  )
}
