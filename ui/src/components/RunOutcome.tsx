// RunOutcome.tsx — What happened, for someone who does not read Scorecards.
//
// A finished run reports span / passes / streak / touch. Those are the right
// numbers for an operator tracking a project toward hands-off delivery, and
// they say nothing to a person who has just asked for their first change.
//
// This states the outcome in the terms the promise was made in: the checks ran,
// they passed, and the change is yours to review. The Scorecard stays directly
// below — this does not replace it, it explains what it means the first time.
import { AlertTriangle, CheckCircle2, Eye, Loader2, XCircle, Zap } from 'lucide-react'
import { ActionButton } from './ActionButton'

export function RunOutcome({
  finished,
  success,
  aborted,
  commitSha,
  branch,
  onSeeChanges,
  quarantined = [],
  spike = false,
}: {
  finished: boolean
  /** null while the run has not reached a verdict yet. */
  success: boolean | null
  aborted: boolean
  commitSha?: string | null
  /** The branch the change landed on, when the run was isolated and committed. */
  branch?: string | null
  onSeeChanges?: (branch: string) => void
  /** Checks that failed and were quarantined — recorded, but not blocking. The
   *  verdict must name them: "your checks passed" is false while one is red. */
  quarantined?: string[]
  /** A spike never lands and its checks gate is fenced off. Reporting it in the
   *  same words as a real demand would sell a guarantee it never made. */
  spike?: boolean
}) {
  if (!finished) {
    return (
      <div className="flex items-start gap-2.5 rounded-panel border border-border bg-panel px-3 py-2.5">
        <Loader2 className="mt-[2px] h-4 w-4 shrink-0 animate-spin text-running" />
        <p className="text-[length:var(--ui-text-body)] text-muted">
          Working. When the change is made, this project's checks run against it — nothing is
          reported done before they pass.
        </p>
      </div>
    )
  }

  if (aborted) {
    return (
      <div className="flex items-start gap-2.5 rounded-panel border border-warn/40 bg-warn/5 px-3 py-2.5">
        <AlertTriangle className="mt-[2px] h-4 w-4 shrink-0 text-warn" />
        <p className="text-[length:var(--ui-text-body)] text-muted">
          <span className="text-primary">Stopped before finishing.</span> Nothing was reported as
          done. Any edits it had already made are still in the working tree.
        </p>
      </div>
    )
  }

  if (!success) {
    return (
      <div className="flex items-start gap-2.5 rounded-panel border border-error/40 bg-error/5 px-3 py-2.5">
        <XCircle className="mt-[2px] h-4 w-4 shrink-0 text-error" />
        <p className="text-[length:var(--ui-text-body)] text-muted">
          <span className="text-primary">The checks did not pass.</span> The change was not
          committed and was not merged. The attempts below show what was tried and what failed.
        </p>
      </div>
    )
  }

  if (spike) {
    return (
      <div className="flex items-start gap-2.5 rounded-panel border border-warn/40 bg-warn/5 px-3 py-2.5">
        <Zap className="mt-[2px] h-4 w-4 shrink-0 text-warn" />
        <p className="text-[length:var(--ui-text-body)] text-muted">
          <span className="text-primary">Spike finished.</span> A spike is throwaway
          exploration: the checks gate is deliberately relaxed and nothing is landed.
          Read what it found — do not read this as a verified change.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      <div className="flex items-start gap-2.5 rounded-panel border border-live/40 bg-live/5 px-3 py-2.5">
        <CheckCircle2 className="mt-[2px] h-4 w-4 shrink-0 text-live" />
        <p className="text-[length:var(--ui-text-body)] text-muted">
          <span className="text-primary">
            {quarantined.length > 0
              ? "Done — this project's blocking checks passed."
              : "Done — this project's checks passed."}
          </span>{' '}
          {quarantined.length > 0
            ? `${quarantined.join(', ')} failed but ${quarantined.length === 1 ? 'is' : 'are'} quarantined, so ${quarantined.length === 1 ? 'it' : 'they'} did not block this. `
            : ''}
          {commitSha ? 'The change is committed. ' : ''}
          {/* The one thing ALC deliberately does not do. Saying it here is the
              difference between a tool that is trusted and one that is trusted
              too much. */}
          ALC verified that it builds and your checks pass; it did not verify that
          it is <em>right</em>. Read the diff.
        </p>
      </div>
      {/* "Read the diff" was an instruction with nowhere to go. The button shows
          only when there is a branch to read — a run against the working tree has
          no diff of its own to open. */}
      {branch && onSeeChanges && (
        <ActionButton
          onClick={() => onSeeChanges(branch)}
          tone="ghost"
          size="md"
          className="mt-2 self-start"
        >
          <Eye className="h-3.5 w-3.5" />
          See what changed
        </ActionButton>
      )}
    </div>
  )
}
