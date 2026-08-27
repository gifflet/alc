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
import { ArrowRight, Loader2, ShieldCheck } from 'lucide-react'
import { ApiError } from '../api/client'
import { useStartExec } from '../app/useStartExec'

export function StartWork({ compact = false }: { compact?: boolean }) {
  const [goal, setGoal] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const start = useStartExec()

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

      <p className="mt-2.5 flex items-start gap-1.5 text-[length:var(--ui-text-label)] text-faint">
        <ShieldCheck className="mt-[1px] h-3 w-3 shrink-0 text-live" />
        {/* The promise in the words of the outcome. "Assurance Loop" is the
            mechanism; this is what it buys you. */}
        ALC plans the work, runs it, and runs this project's checks before
        calling anything done. A change that fails them is never reported as
        finished.
      </p>

      {error && <p className="mt-2 text-[length:var(--ui-text-label)] text-error">{error}</p>}
    </div>
  )
}
