// Team.tsx — The hired roster (Archetype Packs), hire controls, and Mix Health.
//
// The UI never reimplements the core: the roster and Mix Health are exactly
// what GET /team returns (service.team_roster mirroring cli.py's
// `_team_roster`). The five archetype names below are a static mirror of the
// backend's PACKS registry (src/alc/packs.py) — Wave 2 ships no metadata
// endpoint for them, so hard-coding the same five names here is the direct,
// boring option instead of a new endpoint just to list them.
import { useState } from 'react'
import { Archive, UserMinus, UserPlus, Users } from 'lucide-react'
import { ApiError } from '../api/client'
import { useHireArchetype, useRemoveMember, useRetireMember, useTeam } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { formatCost } from '../lib/format'
import { formatNetLines } from '../lib/scorecard'
import { ActionButton } from '../components/ActionButton'
import { ConfirmDialog } from '../components/Dialog'
import { Loading, Pill } from '../components/primitives'
import { StatusDot } from '../components/StatusDot'
import type { Tone } from '../components/StatusDot'
import type { ArchetypeSpend, LoopStatus, MixHealth, TeamMember } from '../api/types'

const ARCHETYPES = ['builder', 'sweeper', 'maintainer', 'grower', 'prototyper'] as const

// Static mirror of packs.py's PACK_DESCRIPTIONS, same wording — the junior
// operator's finding: five bare "Hire X" buttons made choosing an archetype
// pure guesswork. A name is not a description, least of all an invented one.
const ARCHETYPE_DESCRIPTION: Record<(typeof ARCHETYPES)[number], string> = {
  builder: 'Turns prototypes into production-quality work: test authoring, live QA, and a hardened ship flow.',
  sweeper: 'Cleans up: simplifies code, removes dead weight, and unships features safely.',
  maintainer: 'Keeps a mature system safe: security patrol, dependency care, and refresh loops.',
  grower: 'Sweeps issues and errors into work: a listen specialist you point at your feedback.',
  prototyper: 'Churns out throwaway explorations: spike first, keep only what survives.',
}

const STATUS_TONE: Record<LoopStatus, Tone> = {
  pending: 'idle',
  running: 'running',
  stopped: 'error',
}

function apiMessage(error: unknown): string | null {
  if (error instanceof ApiError) return error.message
  return error ? 'Request failed.' : null
}

function MemberCard({
  member,
  onRetire,
  onRemove,
}: {
  member: TeamMember
  onRetire: (archetype: string) => void
  onRemove: (archetype: string) => void
}) {
  const archived = member.retired_loops.length > 0
  return (
    <div className="rounded-panel border border-border bg-panel p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="flex min-w-0 flex-col">
            <span className="text-[length:var(--ui-text-body)] font-medium capitalize text-primary">{member.archetype}</span>
            {/* What this member IS — the roster listed five file paths and
                nothing else, which reads as noise to anyone who does not live
                in .alc/. */}
            <span className="text-[length:var(--ui-text-label)] leading-snug text-faint">
              {ARCHETYPE_DESCRIPTION[member.archetype as (typeof ARCHETYPES)[number]] ?? ''}
            </span>
          </span>
          <span className="text-[length:var(--ui-text-label)] text-faint">
            {member.files.length} file{member.files.length === 1 ? '' : 's'}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {/* "Archive loops", not "Retire": the action archives a member's
              LOOPS and nothing else — the member stays hired. The old verb
              promised a departure it never performed, and an operator who
              archived a loop then read the disabled "Retire" + unchanged
              roster as the app being broken (dogfood: the retire question).
              Post-archive the button gives way to a state, not a dead
              control. A pack with no loops (live or archived) shows NOTHING
              here: its earlier disabled-button form sat next to the badge as
              two different renderings of what read as one state, and a
              control that can never fire is noise, not information. */}
          {member.loops.length > 0 ? (
            <ActionButton
              aria-label={`Archive ${member.archetype} loops`}
              onClick={() => onRetire(member.archetype)}
              tone="ghost"
              size="sm"
            >
              <Archive className="h-3 w-3" />
              Archive loops
            </ActionButton>
          ) : archived ? (
            <Pill tone="idle">loops archived</Pill>
          ) : null}
          {/* The exit "Archive loops" is not: membership is "any pack file on
              disk", so an operator who tried a pack had no way off the roster
              from either surface. Removal deletes only files still identical
              to the pack defaults (customised ones are kept and reported), so
              it cannot destroy work — and hire rewrites what it removed. */}
          <ActionButton
            aria-label={`Remove ${member.archetype}`}
            onClick={() => onRemove(member.archetype)}
            tone="error"
            size="sm"
          >
            <UserMinus className="h-3 w-3" />
            Remove
          </ActionButton>
        </div>
      </div>
      <ul className="mt-1.5 flex flex-col gap-0.5">
        {member.files.map((f) => (
          <li key={f} className="truncate font-mono text-[length:var(--ui-text-label)] text-muted">
            {f}
          </li>
        ))}
      </ul>
      {(member.loops.length > 0 || archived) && (
        <div className="mt-2 flex flex-col gap-1 border-t border-border/15 pt-2">
          {member.loops.map((l) => (
            <div key={l.name} className="flex items-center gap-2 text-[length:var(--ui-text-body)]">
              <StatusDot tone={STATUS_TONE[l.status]} pulse={l.status === 'running'} />
              <span className="text-muted">{l.name}</span>
              <Pill tone={STATUS_TONE[l.status]}>{l.status}</Pill>
              <span className="tabular text-[length:var(--ui-text-label)] text-faint">cycle {l.cycle}</span>
            </div>
          ))}
          {member.retired_loops.map((name) => (
            <div key={name} className="flex items-center gap-2 text-[length:var(--ui-text-body)]">
              <StatusDot tone="idle" />
              <span className="text-muted">{name}</span>
              <Pill tone="idle">archived</Pill>
              <span className="text-[length:var(--ui-text-label)] text-faint">in loops/retired/</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** [core]/[secondary]/[off-mix] against the stage's target mix — or null
 * when there is no stage to judge against, or the archetype is unset (never
 * singled out, matching stagepolicy.validate_stage_mix). */
function mixLabel(health: MixHealth, archetype: string | null): 'core' | 'secondary' | 'off-mix' | null {
  if (!health.stage || archetype === null) return null
  if (health.core.includes(archetype)) return 'core'
  if (health.secondary.includes(archetype)) return 'secondary'
  return 'off-mix'
}

const MIX_TONE: Record<'core' | 'secondary' | 'off-mix', Tone> = {
  core: 'live',
  secondary: 'accent',
  'off-mix': 'warn',
}

function SpendRow({ spend, health }: { spend: ArchetypeSpend; health: MixHealth }) {
  const label = mixLabel(health, spend.archetype)
  return (
    <tr className="h-[var(--ui-row-h)] border-b border-border/15">
      <td className="px-2 text-muted">{spend.archetype ?? '(none)'}</td>
      {health.stage && (
        <td className="px-2">{label && <Pill tone={MIX_TONE[label]}>{`[${label}]`}</Pill>}</td>
      )}
      <td className="px-2 tabular text-muted">{spend.runs}</td>
      <td className="px-2 tabular text-muted">{spend.span}</td>
      <td className="px-2 tabular text-muted">{formatCost(spend.cost_usd)}</td>
      <td className="px-2 tabular text-muted">{formatNetLines(spend.net_lines)}</td>
    </tr>
  )
}

function MixHealthSection({ health }: { health: MixHealth }) {
  if (health.total_runs === 0) {
    return <p className="text-[length:var(--ui-text-body)] text-faint">No data yet — no archived runs.</p>
  }
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[length:var(--ui-text-body)] text-muted">
        {health.stage ? (
          <>
            Stage: <span className="text-primary">{health.stage}</span>
          </>
        ) : (
          'No stage declared — plain breakdown, not judged against a mix.'
        )}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] border-collapse text-[length:var(--ui-text-body)]">
          <thead>
            <tr className="border-b border-border text-left text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
              <th className="px-2 py-1 font-medium">Archetype</th>
              {health.stage && <th className="px-2 py-1 font-medium">Mix</th>}
              <th className="px-2 py-1 font-medium">Runs</th>
              <th className="px-2 py-1 font-medium">Span</th>
              <th className="px-2 py-1 font-medium">Cost</th>
              <th className="px-2 py-1 font-medium">Net lines</th>
            </tr>
          </thead>
          <tbody>
            {health.by_archetype.map((s) => (
              <SpendRow key={s.archetype ?? '(none)'} spend={s} health={health} />
            ))}
          </tbody>
        </table>
      </div>
      {health.idle_core.length > 0 && (
        <ul className="flex flex-col gap-1">
          {health.idle_core.map((idle) => (
            <li key={idle.archetype} className="flex items-center gap-1.5 text-[length:var(--ui-text-body)]">
              <Pill tone="warn">{idle.archetype}</Pill>
              <span className="text-muted">
                {idle.hired ? 'hired but never exercised' : 'not hired'} — {idle.hint}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function Team() {
  const id = useProjectId()
  const { data, isLoading } = useTeam(id)
  const hire = useHireArchetype(id)
  const retire = useRetireMember(id)
  const remove = useRemoveMember(id)
  const [hiring, setHiring] = useState<string | null>(null)
  const [retiring, setRetiring] = useState<string | null>(null)
  const [removing, setRemoving] = useState<string | null>(null)
  // One outcome line for archive AND remove: both end in "the dialog closed,
  // now what happened?" — a single slot keeps the answers from stacking.
  const [notice, setNotice] = useState<string | null>(null)

  if (isLoading) return <Loading />

  const members = data?.members ?? []
  const health = data?.mix_health
  const hired = new Set(members.map((m) => m.archetype))
  const available = ARCHETYPES.filter((a) => !hired.has(a))

  const doHire = (archetype: string) => {
    setHiring(archetype)
    hire.mutate({ archetype }, { onSettled: () => setHiring(null) })
  }

  const confirmRetire = () => {
    if (!retiring) return
    const who = retiring
    retire.mutate(who, {
      onSuccess: (result) => {
        setRetiring(null)
        // The CLI says "Retired 'x': <paths>" or "'x' has no loop(s) on disk to
        // retire." The UI said nothing at all — the dialog closed, the roster
        // was unchanged, and a 200 looked like a broken app. Say the same thing.
        const n = result.moved.length
        setNotice(
          n === 0
            ? `${who} had no loops on disk — nothing to archive.`
            : `Archived ${n === 1 ? "1 loop" : `${n} loops`} from ${who} into loops/retired/. ` +
              `${who} stays on the roster: its blueprints, flows and specialists are untouched.`,
        )
      },
    })
  }

  const confirmRemove = () => {
    if (!removing) return
    const who = removing
    remove.mutate(who, {
      onSuccess: (result) => {
        setRemoving(null)
        // Same contract as the CLI's `alc team remove` output: what was
        // deleted, what was kept, and the roster consequence of the kept half.
        const n = result.removed.length
        const k = result.kept.length
        setNotice(
          n === 0 && k === 0
            ? `${who} had no pack files on disk — nothing to remove.`
            : k > 0
              ? `Removed ${n} file${n === 1 ? '' : 's'} from ${who}. Kept ${k} customised file${k === 1 ? '' : 's'} (${result.kept.join(', ')}) — ${who} stays on the roster because of ${k === 1 ? 'it' : 'them'}.`
              : `Removed ${who} (${n} file${n === 1 ? '' : 's'}). Hire again anytime.`,
        )
      },
    })
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <header className="flex items-center gap-3">
        <Users className="h-4 w-4 text-muted" />
        <h1 className="text-[14px] font-medium text-primary">Team</h1>
      </header>

      <section>
        <h2 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Roster</h2>
        {members.length === 0 ? (
          <p className="text-[length:var(--ui-text-body)] text-faint">No archetypes hired yet.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {members.map((m) => (
              <MemberCard key={m.archetype} member={m} onRetire={setRetiring} onRemove={setRemoving} />
            ))}
          </div>
        )}
        {apiMessage(retire.error ?? remove.error) && (
          <p className="mt-2 text-[length:var(--ui-text-label)] text-error">
            {apiMessage(retire.error ?? remove.error)}
          </p>
        )}
        {notice && !retire.error && !remove.error && (
          <p className="mt-2 text-[length:var(--ui-text-label)] text-muted" role="status">
            {notice}
          </p>
        )}
      </section>

      {available.length > 0 && (
        <section>
          {/* Named for the CONTENT, not the verb: each row carries its own
              Hire button now, so a section called "Hire" labelled nothing —
              and the CLI already says "Available packs:", so both surfaces
              use one word for one thing. */}
          <h2 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
            Available packs
          </h2>
          {/* A grid, not the button era's flex-wrap it replaced: wrap made each
              row size to its content, so on a desktop the cards sat side by
              side at five different widths. The Dashboard's responsive-grid
              idiom keeps them equal — one column on a phone, two on a desktop
              panel, three when the window is wide. */}
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {/* The same row anatomy the roster establishes one section above —
                name leading, description under it, a compact action on the
                right — because an available archetype is the SAME object as a
                hired one, in a different state. The first pass rendered five
                accent CTAs with orphaned captions floating between them: all
                the visual weight on the action, none on the information a
                chooser actually reads, and only reading order said which
                caption belonged to which button. */}
            {available.map((a) => (
              <div
                key={a}
                className="flex items-center gap-3 rounded-panel border border-border bg-panel p-3"
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="text-[length:var(--ui-text-body)] font-medium capitalize text-primary">
                    {a}
                  </span>
                  <span className="text-[length:var(--ui-text-label)] leading-snug text-faint">
                    {ARCHETYPE_DESCRIPTION[a]}
                  </span>
                </span>
                <ActionButton
                  aria-label={`Hire ${a}`}
                  tone="accent"
                  size="sm"
                  onClick={() => doHire(a)}
                  disabled={hire.isPending && hiring === a}
                  className="shrink-0"
                >
                  <UserPlus className="h-3 w-3" />
                  Hire
                </ActionButton>
              </div>
            ))}
          </div>
          {hire.isError && <p className="mt-2 text-[length:var(--ui-text-label)] text-error">{apiMessage(hire.error)}</p>}
        </section>
      )}

      <section>
        <h2 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Mix Health</h2>
        {health && <MixHealthSection health={health} />}
      </section>

      {retiring && (
        <ConfirmDialog
          title={`Archive ${retiring}'s loops?`}
          message={`This archives ${retiring}'s loop(s) into loops/retired/. Nothing is deleted, and ${retiring} stays on the roster — its blueprints, flows and specialists are left alone.`}
          confirmLabel="Archive loops"
          tone="accent"
          onConfirm={confirmRetire}
          onCancel={() => setRetiring(null)}
        />
      )}
      {removing && (
        <ConfirmDialog
          title={`Remove ${removing}?`}
          message={`This deletes ${removing}'s pack files that still match the pack defaults — anything you customised is kept and listed. You can hire ${removing} again at any time.`}
          confirmLabel="Remove"
          onConfirm={confirmRemove}
          onCancel={() => setRemoving(null)}
        />
      )}
    </div>
  )
}
