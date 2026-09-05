// Dashboard.tsx — The project's health panel.
//
// Deliberately NOT an index of the other views: Queue and Loops cards were cut
// because the Queue, Loops and Inbox screens answer those questions with more
// detail and an action attached. What remains is what only this screen answers —
// the Scorecard trend, engine health, team mix and the cron schedule — plus
// Recent runs, kept as the one shortcut worth having (it is what lets Runs leave
// the mobile bar). Every card is a live query invalidated over WS.
import { useState } from 'react'
import { Users, UserPlus, Activity, CalendarClock, ClipboardList, Cpu, Gauge, Inbox as InboxIcon, PieChart } from 'lucide-react'
import {
  useAudit,
  useEngines,
  useInbox,
  useQueue,
  useRuns,
  useSchedule,
  useScorecard,
  useTeam,
} from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { openView } from '../components/ActivityBar'
import { ActionButton } from '../components/ActionButton'
import { uiStore } from '../app/uiStore'
import { formatCost } from '../lib/format'
import { formatNetLines, scorecardHistory } from '../lib/scorecard'
import type { ScorecardPoint } from '../lib/scorecard'
import { Card, Metric, Pill } from '../components/primitives'
import { StartWork } from '../components/StartWork'
import { EmptyState } from '../components/EmptyState'
import { RelativeTime } from '../components/RelativeTime'
import { StatusDot } from '../components/StatusDot'
import type { InboxItem, MixHealth } from '../api/types'

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

/** One line per metric, matching docs/concepts/scorecard. These are invented
 * words — span, passes, streak, touch — and the card showed eight of them with
 * no legend, three of them reading 3, which invites the reading that they are
 * one thing. */
const SCORECARD_HINT = {
  span: 'Number of checks that passed at the end of the run — more checks passing per prompt means more verified work per prompt.',
  passes: 'Engine turns spent reaching done. Lower is better; a climbing count means the loop is doing your thinking.',
  streak: 'Runs that landed one-shot, with zero repairs. Higher is better.',
  touch: 'Times a human had to step in. Lower is better — Touch to 0 is the north star.',
  reports: 'Archived run reports counted here.',
  ok: 'Runs whose checks all passed.',
  failed: 'Runs that ended with a check still failing.',
  netLines: 'Lines added minus lines deleted across these runs. Negative is good: deletion counts as delivery.',
} as const

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
            <Metric label="span" value={s.span_total} tone="live" hint={SCORECARD_HINT.span} />
            <Metric label="passes" value={s.passes_total} hint={SCORECARD_HINT.passes} />
            <Metric label="streak" value={s.streak_total} hint={SCORECARD_HINT.streak} />
            <Metric
              label="touch"
              value={s.touch_total}
              tone={s.touch_total > 0 ? 'error' : undefined}
              hint={SCORECARD_HINT.touch}
            />
            <Metric label="reports" value={s.reports} hint={SCORECARD_HINT.reports} />
            <Metric label="ok" value={s.successes} tone="live" hint={SCORECARD_HINT.ok} />
            <Metric
              label="failed"
              value={s.failures}
              tone={s.failures > 0 ? 'error' : undefined}
              hint={SCORECARD_HINT.failed}
            />
            <Metric
              label="net lines"
              value={netLines ?? '—'}
              tone={s.net_lines_total != null && s.net_lines_total < 0 ? 'live' : undefined}
              hint={SCORECARD_HINT.netLines}
            />
          </div>
          {/* A hover title is invisible on a touch screen, and half this project's
              use is on a phone. This one line carries the part you cannot work
              without: which direction is good. */}
          <p className="mt-2 text-[length:var(--ui-text-label)] text-faint">
            Span and streak: higher is better. Passes and touch: lower is better — the goal is touch 0.
          </p>
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
      className="inline-flex min-h-[var(--ui-control-h)] items-center px-1 text-[length:var(--ui-text-label)] text-accent transition-colors duration-120 hover:underline"
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
                className="flex min-h-[var(--ui-row-h)] w-full items-center gap-2 text-left text-[length:var(--ui-text-body)] transition-colors duration-120 hover:bg-hover"
              >
                <StatusDot tone={r.finished ? 'idle' : 'running'} pulse={!r.finished} />
                {/* Same shape as the Runs view: the task leads, the stem sits
                    under it as the address you would paste into `alc runs`.
                    This card used to show kind + stem only, and the stem is
                    truncated here — so every row read
                    "run  20260830T041713-run-chore-in-d…" and the one part that
                    told them apart was the part removed. */}
                <span className="flex min-w-0 flex-1 flex-col justify-center leading-tight">
                  <span className="truncate text-muted" title={r.title || r.stem}>
                    {r.title || r.stem}
                  </span>
                  {r.title && (
                    <span className="truncate font-mono text-[length:var(--ui-text-label)] text-faint">
                      {r.unit ? `${r.unit} · ` : ''}
                      {r.stem}
                    </span>
                  )}
                </span>
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
          <div key={e.name} className="flex min-w-0 items-center gap-2 text-[length:var(--ui-text-body)]">
            <StatusDot tone={e.healthy ? 'live' : 'error'} />
            {/* min-w-0 + truncate: at tablet widths the name used to wrap
                mid-word ("claude-" / "code") against the pill and type. */}
            <span className="min-w-0 truncate text-primary">{e.name}</span>
            {e.default && <Pill tone="accent">default</Pill>}
            <span className="ml-auto shrink-0 font-mono text-[length:var(--ui-text-label)] text-faint">{e.type}</span>
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
        /* This card used to spend the primary screen saying a feature you never
           opted into is not running, in two words nothing on the page defines.
           If it is going to take the space, it has to say what declaring a stage
           would buy and how to do it. */
        <div className="flex flex-col gap-2 text-[length:var(--ui-text-body)] text-faint">
          <p className="text-muted">
            No stage declared, so these {health.total_runs} run{health.total_runs === 1 ? '' : 's'} are
            not measured against any target.
          </p>
          <p>
            Declare your product's stage and this card reports how much of your recent
            work matched the mix that stage expects. Advisory — it never changes how a
            run executes.
          </p>
          {/* An ACTION, not YAML homework: the old copy told a dashboard user
              to hand-edit .alc/manifest.yaml (round 12). The Manifest form has
              the stage field. */}
          <div>
            <ActionButton
              aria-label="Declare the stage in the Manifest"
              tone="ghost"
              size="sm"
              onClick={() =>
                uiStore.openTab({
                  target: { type: 'source', resource: 'manifest', name: 'manifest' },
                  title: 'manifest.yaml',
                })
              }
            >
              Declare stage
            </ActionButton>
          </div>
        </div>
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

/** The roster, on the front page. The dashboard had no Team presence at all —
 * a user wanting to hire or check their agents had zero doors from the
 * product's front page (round 12). Hired members show their loops' live
 * state; the available count is the hire door. */
function TeamCard() {
  const id = useProjectId()
  const { data } = useTeam(id)
  const members = data?.members ?? []
  const available = 5 - members.length

  return (
    <Card title="Team" icon={Users} action={<LinkButton onClick={() => openView('team')} />}>
      <div className="flex flex-col gap-1.5">
        {members.length === 0 ? (
          <p className="text-[length:var(--ui-text-body)] text-faint">
            No agents hired yet — five prebuilt packs are ready to work.
          </p>
        ) : (
          members.map((m) => (
            <div key={m.archetype} className="flex min-w-0 items-center gap-2 text-[length:var(--ui-text-body)]">
              <StatusDot
                tone={m.loops.some((l) => l.status === 'running') ? 'running' : 'idle'}
                pulse={m.loops.some((l) => l.status === 'running')}
              />
              <span className="min-w-0 truncate capitalize text-primary">{m.archetype}</span>
              {m.retired_loops.length > 0 && <Pill tone="idle">loops archived</Pill>}
              {m.loops.map((l) => (
                <Pill key={l.name} tone={l.status === 'running' ? 'running' : l.status === 'stopped' ? 'error' : 'idle'}>
                  {l.name}
                </Pill>
              ))}
            </div>
          ))
        )}
        {available > 0 && (
          <div className="mt-0.5">
            <ActionButton
              aria-label="Hire an archetype pack"
              tone={members.length === 0 ? 'accent' : 'ghost'}
              size="sm"
              onClick={() => openView('team')}
            >
              <UserPlus className="h-3 w-3" />
              {available} pack{available === 1 ? '' : 's'} available
            </ActionButton>
          </div>
        )}
      </div>
    </Card>
  )
}

const NEEDS_YOU_LABEL: Record<InboxItem['kind'], string> = {
  failure: 'failure',
  branch: 'to land',
  loop: 'loop stopped',
}

/** Work that is waiting on a decision, at the top of the page.
 *
 * Every other card on this screen reports on work that already happened; this
 * is the only one about work that is stopped until a human moves it. It used to
 * be reachable only as a number on a rail icon, while "Mix Health: no stage
 * declared" got a full card — so the page gave its most prominent space to the
 * thing that needed nobody. Renders NOTHING when the inbox is empty: a card
 * saying "no decisions pending" is noise on a screen whose job is signal.
 *
 * Deliberately no Land/Discard here. Those actions carry confirmation dialogs
 * that state what landing an unverified branch means, and a second copy of that
 * logic is a second place for it to drift out of agreement with the Inbox.
 */
function NeedsYouCard() {
  const id = useProjectId()
  const { data } = useInbox(id)
  const items = data?.items ?? []
  if (items.length === 0) return null
  return (
    <Card
      title={`Needs you (${items.length})`}
      icon={InboxIcon}
      action={
        <button
          type="button"
          onClick={() => openView('inbox')}
          className="min-h-[var(--ui-control-h)] rounded-panel border border-border px-2 text-[length:var(--ui-text-label)] text-muted transition-colors duration-120 hover:bg-hover"
        >
          Open Inbox
        </button>
      }
    >
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.id} className="flex min-w-0 flex-col gap-0.5">
            <div className="flex min-w-0 items-center gap-2">
              <StatusDot tone={item.kind === 'failure' || item.verified === false ? 'error' : 'accent'} />
              <span className="min-w-0 flex-1 truncate text-[length:var(--ui-text-body)] text-primary">
                {item.title}
              </span>
              {/* Same wording as the Inbox row, including the unverified
                  override: two screens describing one branch two ways is how an
                  operator ends up trusting the wrong one. */}
              <span
                className={`shrink-0 text-[length:var(--ui-text-label)] uppercase tracking-wide ${
                  item.verified === false ? 'text-error' : 'text-faint'
                }`}
              >
                {item.verified === false ? 'unverified' : NEEDS_YOU_LABEL[item.kind]}
              </span>
            </div>
            <p className="truncate pl-4 text-[length:var(--ui-text-label)] text-muted">{item.reason}</p>
          </li>
        ))}
      </ul>
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
          className="min-h-[var(--ui-control-h)] rounded-panel border border-border bg-base px-1.5 text-[length:var(--ui-text-label)] text-primary outline-none focus:border-accent"
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

/** Read-only view of the host crontab's ALC-scheduled entries.
 * Installing/removing a schedule stays a CLI-only operation — the card
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
      {/* Above StartWork on purpose: a branch waiting on a decision outranks
          starting more work, and the card removes itself when nothing is
          waiting, so the calm case is unchanged. */}
      <div className="md:col-span-2 xl:col-span-3 empty:hidden">
        <NeedsYouCard />
      </div>
      <div className="md:col-span-2 xl:col-span-3">
        <StartWork />
      </div>
      <ScorecardCard />
      <TeamCard />
      <EnginesCard />
      <RunsCard />
      <MixHealthCard />
      <AuditCard />
      <ScheduleCard />
    </div>
  )
}
