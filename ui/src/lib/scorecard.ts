// scorecard.ts — Derive a per-report history from archived (done) queue tasks.
//
// The aggregate scorecard hides trend; this turns the reported done tasks into an
// oldest→newest series the dashboard renders as a compact CSS bar chart.
import type { DoneTask } from '../api/types'

export interface ScorecardPoint {
  stem: string
  span: number
  success: boolean
}

/** The last `limit` reported done tasks as chart points (oldest first). */
export function scorecardHistory(done: DoneTask[], limit = 12): ScorecardPoint[] {
  return done
    .filter((d): d is DoneTask & { report: NonNullable<DoneTask['report']> } => d.report !== null)
    .sort((a, b) => a.mtime - b.mtime)
    .slice(-limit)
    .map((d) => ({ stem: d.stem, span: d.report.scorecard.span, success: d.report.success }))
}
