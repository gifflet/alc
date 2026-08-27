// StartWork.tsx — One field, for someone who has not learned the vocabulary yet.
//
// The app offers six ways to start work: Run, Spike, Enqueue, Explore, LoopRun
// and Conduct. Each is the right answer to a question a newcomer cannot ask
// yet, because telling them apart means already holding the model.
//
// This asks for the thing they do know — what they want done — and hands it to
// the Conductor, which is the part of ALC whose job is deciding which units to
// run. Engine and tier come from the manifest. The other five entry points stay
// exactly where they are for anyone who wants to drive directly.
//
// The guarantee is stated, not taught: the line under the field says the change
// is verified before it is reported done. That is the whole promise, in the
// words of the outcome rather than the mechanism.
import { useState } from 'react'
import { AlertTriangle, ArrowRight, FolderGit2, Loader2, ShieldCheck } from 'lucide-react'
import { ApiError } from '../api/client'
import { useChecksAudit, useEngines } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'

/** What this project can actually promise, read rather than assumed.
 *
 *  The first version of this component stated the guarantee as an absolute:
 *  "a change that fails them is never reported as finished". That sentence is
 *  false in states the product genuinely has — a quarantined check fails and
 *  the run still succeeds (assurance.py), a smoke-only Blueprint verifies
 *  nothing but a `true` placeholder, and a `mock` engine makes no model call at
 *  all. Claiming a guarantee that did not run is the one thing this product
 *  forbids of itself, so the claim is now derived from the project. */
function useGuarantee(): { tone: 'ok' | 'warn'; text: string } {
  const id = useProjectId()
  const { data: engines } = useEngines(id)
  const { data: audit } = useChecksAudit(id)

  const defaultEngine = (engines ?? []).find((e) => e.default)
  if (defaultEngine?.type === 'mock') {
    return {
      tone: 'warn',
      text: 'This project runs on the mock engine — it makes no model call, changes nothing and verifies nothing. Set a real engine in the Manifest before trusting a result.',
    }
  }

  const smokeOnly = audit?.smoke_only_blueprints ?? []
  if (audit && smokeOnly.length > 0 && (audit.check_sets ?? []).length === 0) {
    return {
      tone: 'warn',
      text: 'This project has no real checks yet — only a placeholder that always passes. ALC will run the work, but nothing will verify it until you wire up your tests.',
    }
  }

  return {
    tone: 'ok',
    text: "ALC plans the work, runs it, and runs this project's own checks before calling anything done.",
  }
}

export function StartWork({ compact = false }: { compact?: boolean }) {
  const [goal, setGoal] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const start = useStartExec()
  const guarantee = useGuarantee()

  const submit = async () => {
    const trimmed = goal.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setError(null)
    try {
      // Nothing else is passed: engine and tier come from the manifest, which
      // is where the project already declared them. Asking again would be
      // asking a question whose answer is on file.
      await start('conduct', { goal: trimmed })
      setGoal('')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={compact ? '' : 'rounded-panel border border-border bg-panel p-4'}>
      {!compact && (
        <h2 className="text-[length:var(--ui-text-title)] font-medium text-primary">
          What should the agent work on?
        </h2>
      )}

      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
          }}
          placeholder="e.g. fix the crash when a config file is missing"
          aria-label="What should the agent work on?"
          disabled={busy}
          className="min-h-[var(--ui-control-h)] min-w-0 flex-1 rounded-panel border border-border bg-base px-3 text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent disabled:opacity-50"
        />
        <button
          type="button"
          onClick={submit}
          disabled={!goal.trim() || busy}
          className="flex min-h-[var(--ui-control-h)] shrink-0 items-center justify-center gap-1.5 rounded-panel border border-accent/60 bg-accent/10 px-4 text-[length:var(--ui-text-body)] text-accent transition-colors duration-120 hover:bg-accent/20 disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRight className="h-3.5 w-3.5" />}
          Start
        </button>
      </div>

      <div className="mt-2.5 flex flex-col gap-1.5 text-[length:var(--ui-text-label)] text-faint">
        <p className="flex items-start gap-1.5">
          {guarantee.tone === 'ok' ? (
            <ShieldCheck className="mt-[1px] h-3 w-3 shrink-0 text-live" />
          ) : (
            <AlertTriangle className="mt-[1px] h-3 w-3 shrink-0 text-warn" />
          )}
          {guarantee.text}
        </p>
        <p className="flex items-start gap-1.5">
          <FolderGit2 className="mt-[1px] h-3 w-3 shrink-0 text-warn" />
          {/* Saying only "it is verified" and staying silent about the files is
              the more dangerous half-truth: someone types into this box the way
              they type into a search bar, and it edits their repository. */}
          Edits happen in your working tree, on your current branch — commit or
          stash anything you do not want touched.
        </p>
      </div>

      {error && <p className="mt-2 text-[length:var(--ui-text-label)] text-error">{error}</p>}
    </div>
  )
}
