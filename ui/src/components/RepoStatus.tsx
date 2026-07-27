// RepoStatus.tsx — The StatusBar's live repo / working-tree cluster.
//
// A standalone component (SRP): it owns nothing but reading useWorktreeStatus and
// rendering the compact cluster, so it is testable with installFetch +
// renderWithProviders — no useWs mocking. Freshness is entirely push-driven: the
// backend's watch.py emits a debounced `worktree_changed` that invalidates the
// worktree query, so a split-screen edit/commit/stash updates this in place.
import { GitBranch } from 'lucide-react'
import { useWorktreeStatus } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { StatusDot } from './StatusDot'

export function RepoStatus() {
  const id = useProjectId()
  const { data } = useWorktreeStatus(id)

  // Off-git (or still loading): there is simply nothing to show.
  if (!data?.available) return null

  const { dirty, branch, detached, upstream, ahead, behind, untracked } = data

  // The ahead/behind chip appears ONLY when git could compute the counts
  // (ahead !== null — which also excludes the no-upstream and tracking-ref-gone
  // cases), and only renders the non-zero halves. In-sync (0/0) shows no chip.
  const halves = ahead !== null ? [ahead > 0 ? `↑${ahead}` : '', (behind ?? 0) > 0 ? `↓${behind}` : ''] : []
  const aheadBehind = halves.filter(Boolean).join(' ')

  // The honesty tooltip is REQUIRED by the no-auto-fetch constraint: ahead/behind
  // are only ever as of the operator's LAST fetch — ALC never fetches on its own.
  const head = detached ? 'detached HEAD' : `on ${branch}`
  let sync: string
  if (upstream === null) {
    sync = 'no upstream configured'
  } else if (ahead !== null) {
    sync = `↑${ahead} ↓${behind} vs ${upstream} as of your last fetch (ALC never fetches)`
  } else {
    // Upstream set but its tracking ref is gone — honest about why there's no count.
    sync = `tracking ${upstream}; ahead/behind unknown until your next fetch`
  }
  const tooltip = `${head} — ${sync}${dirty ? `; ${untracked} untracked` : ''}`

  return (
    <span className="flex items-center gap-1.5 text-[11px]" title={tooltip}>
      <GitBranch className="h-3 w-3 text-muted" />
      <span className={detached ? 'text-faint' : 'text-muted'}>
        {detached ? 'detached' : branch}
      </span>
      {aheadBehind && <span className="tabular text-faint">{aheadBehind}</span>}
      {dirty && (
        <StatusDot
          tone="warn"
          title={`Uncommitted changes outside .alc/${untracked > 0 ? ` — ${untracked} untracked` : ''}`}
        />
      )}
    </span>
  )
}
