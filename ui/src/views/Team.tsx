// Team.tsx — The hired roster (Archetype Packs), hire controls, and Mix Health.
//
// The UI never reimplements the core: the roster and Mix Health are exactly
// what GET /team returns (service.team_roster mirroring cli.py's
// `_team_roster`). The five archetype names below are a static mirror of the
// backend's PACKS registry (src/alc/packs.py) — Wave 2 ships no metadata
// endpoint for them, so hard-coding the same five names here is the direct,
// boring option instead of a new endpoint just to list them.
import { useState } from 'react'
import { UserMinus, UserPlus, Users } from 'lucide-react'
import { ApiError } from '../api/client'
import { useHireArchetype, useRetireMember, useTeam } from '../api/hooks'
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
}: {
  member: TeamMember
  onRetire: (archetype: string) => void
}) {
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
        {/* Retire archives a member's LOOPS and nothing else. Three of the five
            packs ship no loop at all, so for them the button could never do
            anything — it returned 200 with an empty result and the operator was
            left to conclude the app was broken. Say why instead. */}
        <ActionButton
          aria-label={`Retire ${member.archetype}`}
          onClick={() => onRetire(member.archetype)}
          tone="ghost"
          size="sm"
          className="shrink-0"
          disabled={member.loops.length === 0}
          title={
            member.loops.length === 0
              ? `${member.archetype} has no loops on disk — retiring archives loops, and there are none`
              : undefined
          }
        >
          <UserMinus className="h-3 w-3" />
          Retire
        </ActionButton>
      </div>
      <ul className="mt-1.5 flex flex-col gap-0.5">
        {member.files.map((f) => (
          <li key={f} className="truncate font-mono text-[length:var(--ui-text-label)] text-muted">
            {f}
          </li>
        ))}
      </ul>
      {member.loops.length > 0 && (
        <div className="mt-2 flex flex-col gap-1 border-t border-border/15 pt-2">
          {member.loops.map((l) => (
            <div key={l.name} className="flex items-center gap-2 text-[length:var(--ui-text-body)]">
              <StatusDot tone={STATUS_TONE[l.status]} pulse={l.status === 'running'} />
              <span className="text-muted">{l.name}</span>
              <Pill tone={STATUS_TONE[l.status]}>{l.status}</Pill>
              <span className="tabular text-[length:var(--ui-text-label)] text-faint">cycle {l.cycle}</span>
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
  const [hiring, setHiring] = useState<string | null>(null)
  const [retiring, setRetiring] = useState<string | null>(null)
  const [retired, setRetired] = useState<string | null>(null)

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
        setRetired(
          n === 0
            ? `${who} had no loops on disk — nothing to archive.`
            : `Archived ${n === 1 ? "1 loop" : `${n} loops`} from ${who} into loops/retired/. ` +
              `${who} stays on the roster: its blueprints, flows and specialists are untouched.`,
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
              <MemberCard key={m.archetype} member={m} onRetire={setRetiring} />
            ))}
          </div>
        )}
        {apiMessage(retire.error) && (
          <p className="mt-2 text-[length:var(--ui-text-label)] text-error">{apiMessage(retire.error)}</p>
        )}
        {retired && !retire.error && (
          <p className="mt-2 text-[length:var(--ui-text-label)] text-muted" role="status">
            {retired}
          </p>
        )}
      </section>

      {available.length > 0 && (
        <section>
          <h2 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Hire</h2>
          <div className="flex flex-wrap gap-2">
            {available.map((a) => (
              <div key={a} className="flex min-w-0 flex-col gap-1">
                <ActionButton
                  tone="accent"
                  onClick={() => doHire(a)}
                  disabled={hire.isPending && hiring === a}
                  className="self-start capitalize"
                >
                  <UserPlus className="h-3.5 w-3.5" />
                  Hire {a}
                </ActionButton>
                <p className="text-[length:var(--ui-text-label)] leading-snug text-faint">
                  {ARCHETYPE_DESCRIPTION[a]}
                </p>
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
          title={`Retire ${retiring}?`}
          message={`This archives ${retiring}'s loop(s) into loops/retired/. Nothing is deleted, and ${retiring} STAYS on the roster — its blueprints, flows and specialists are left alone.`}
          confirmLabel="Retire"
          onConfirm={confirmRetire}
          onCancel={() => setRetiring(null)}
        />
      )}
    </div>
  )
}
