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

/**
 * Format the scorecard's net-lines total (adds minus dels) with an explicit
 * sign, or `null` when there is no diffstat data to report (an older backend
 * omitting the field, or every archived report lacking a diffstat).
 */
export function formatNetLines(total: number | null | undefined): string | null {
  if (total === null || total === undefined) return null
  if (total > 0) return `+${total}`
  if (total < 0) return `−${Math.abs(total)}`
  return '0'
}
