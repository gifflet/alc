// OnboardPanel.tsx — The harvest-only `alc onboard` proposal + adopt, in Checks.
//
// Surfaces exactly what GET /checks/onboard returns and adopts it with POST
// /checks/onboard/apply — the UI never invents a check. The engine `--assist`
// path stays CLI-only (it spends an engine turn), so an empty proposal points
// the operator at the CLI rather than fabricating anything. The server rebuilds
// the whole proposal on apply; this panel sends only the chosen stage.
import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { ApiError } from '../api/client'
import { useApplyOnboard, useOnboardProposal } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { Pill } from '../components/primitives'
import type { Tone } from '../components/StatusDot'
import type { OnboardApplyResult, ProposedCheck } from '../api/types'

const STAGES = ['pre-pmf', 'growth', 'strong-pmf'] as const

/** The command/shell column for one proposed check. */
function checkForm(check: ProposedCheck): string {
  if (check.command) return check.command.join(' ')
  return check.shell ?? ''
}

/** The status pill for one proposed check. `origin === "engine"` never occurs in
 * UI v1 (assist is CLI-only) but the mapping stays honest: an inferred check is
 * always flagged for review rather than silently trusted. */
function checkStatus(check: ProposedCheck): { label: string; tone: Tone } {
  if (check.origin === 'engine') return { label: 'inferred — review', tone: 'accent' }
  return check.available
    ? { label: 'available', tone: 'live' }
    : { label: 'commented — binary off PATH', tone: 'warn' }
}

function ChecksTable({ checks }: { checks: ProposedCheck[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] border-collapse text-[length:var(--ui-text-body)]">
        <thead>
          <tr className="border-b border-border text-left text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
            <th className="px-2 py-1 font-medium">Check</th>
            <th className="px-2 py-1 font-medium">Command / shell</th>
            <th className="px-2 py-1 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((c) => {
            const status = checkStatus(c)
            return (
              <tr key={c.name} className="h-[var(--ui-row-h)] border-b border-border/15">
                <td className="px-2 font-mono text-primary">{c.name}</td>
                <td className="px-2 font-mono text-[length:var(--ui-text-label)] text-muted">{checkForm(c)}</td>
                <td className="px-2">
                  <Pill tone={status.tone}>{status.label}</Pill>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** The clean-apply summary — what actually got written. The audit and manifest
 * also refresh live (WS), so this is a brief confirmation, not the source of
 * truth. */
function AppliedSummary({ result }: { result: OnboardApplyResult }) {
  const parts: string[] = []
  if (result.sets_added.length > 0) parts.push(`check_sets added: ${result.sets_added.join(', ')}`)
  if (result.blueprints_opted_in.length > 0)
    parts.push(`blueprints opted in: ${result.blueprints_opted_in.join(', ')}`)
  if (result.stage_set) parts.push('stage set')
  return (
    <div className="rounded-panel border border-live/40 bg-live/10 px-3 py-2 text-[length:var(--ui-text-body)] text-live">
      {parts.length > 0 ? `Adopted — ${parts.join('; ')}.` : 'Nothing to adopt.'}
      {result.notes.map((n) => (
        <p key={n} className="mt-0.5 text-[length:var(--ui-text-label)] text-muted">
          {n}
        </p>
      ))}
    </div>
  )
}

/** The 422 violations a blocked apply carried — rendered like the manifest
 * editor's save error (rule + message). */
function ViolationsNote({ error }: { error: ApiError }) {
  return (
    <div className="rounded-panel border border-error/40 bg-error/10 px-3 py-2 text-[length:var(--ui-text-body)] text-error">
      <p className="font-medium">{error.message}</p>
      {error.violations.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 font-mono text-[length:var(--ui-text-label)] text-error/90">
          {error.violations.map((v, i) => (
            <li key={i}>
              <span className="text-faint">{v.rule}:</span> {v.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function OnboardPanel() {
  const id = useProjectId()
  const [stage, setStage] = useState('') // '' = no stage chosen
  const selectedStage = stage || null
  const { data, isLoading } = useOnboardProposal(id, selectedStage)
  const apply = useApplyOnboard(id)
  const [applied, setApplied] = useState<OnboardApplyResult | null>(null)

  if (isLoading) return <p className="text-[length:var(--ui-text-body)] text-faint">Loading…</p>
  if (!data) return null

  const projectChecks = data.check_sets.project ?? []
  const optInNames = Object.keys(data.blueprint_opt_ins)
  const nothingToOnboard =
    Object.keys(data.check_sets).length === 0 && optInNames.length === 0

  if (nothingToOnboard) {
    // Nothing to adopt — surface the proposal's OWN reason (the backend now says
    // whether the project is already onboarded or simply had nothing to harvest),
    // then the generic CLI hint. Never hard-code "none were harvested": it is
    // wrong once a project is already onboarded.
    return (
      <div className="flex flex-col gap-1.5 text-[length:var(--ui-text-body)] text-faint">
        {data.unknowns.map((note) => (
          <p key={note} className="flex items-start gap-1.5">
            <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{note}</span>
          </p>
        ))}
        <p className="flex items-start gap-1.5">
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            Nothing to onboard here. Run{' '}
            <span className="font-mono text-muted">alc onboard --assist</span> (CLI) to analyze the
            tree with the engine, or add checks by hand.
          </span>
        </p>
      </div>
    )
  }

  const doAdopt = () => {
    setApplied(null)
    apply.mutate(selectedStage, { onSuccess: (result) => setApplied(result) })
  }

  const error = apply.error instanceof ApiError ? apply.error : null

  return (
    <div className="flex flex-col gap-3">
      {projectChecks.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
            Proposed <span className="font-mono">project</span> check_set
          </p>
          <ChecksTable checks={projectChecks} />
        </div>
      )}

      {optInNames.length > 0 && (
        <p className="text-[length:var(--ui-text-body)] text-muted">
          Will insert <span className="font-mono text-primary">check_set: project</span> into:{' '}
          {optInNames.map((name, i) => (
            <span key={name}>
              {i > 0 && ', '}
              <span className="font-mono text-primary">{name}</span>
            </span>
          ))}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint" htmlFor="onboard-stage">
          Stage
        </label>
        <select
          id="onboard-stage"
          value={stage}
          onChange={(e) => setStage(e.target.value)}
          className="rounded-panel border border-border bg-panel px-2 py-1 text-[length:var(--ui-text-body)] text-primary"
        >
          <option value="">none</option>
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={doAdopt}
          disabled={apply.isPending}
          className="flex min-h-[var(--ui-control-h)] items-center gap-1.5 rounded-panel border border-accent/60 bg-accent/10 px-2.5 text-[length:var(--ui-text-body)] text-accent transition-colors duration-120 hover:bg-accent/20 disabled:opacity-40"
        >
          Adopt
        </button>
      </div>

      {selectedStage && data.team_hints.length > 0 && (
        <p className="text-[length:var(--ui-text-body)] text-muted">
          stage <span className="text-primary">{selectedStage}</span> suggests hiring:{' '}
          {data.team_hints.join(', ')}{' '}
          <span className="text-faint">(advisory — a stage never changes execution)</span>
        </p>
      )}

      {error ? <ViolationsNote error={error} /> : applied && <AppliedSummary result={applied} />}
    </div>
  )
}
