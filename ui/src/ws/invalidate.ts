// invalidate.ts — Map a WS message to the query keys it invalidates.
//
// Pure function so the fan-out policy is unit-tested without React or a live
// socket. WsProvider calls queryClient.invalidateQueries for each key returned.
import type { QueryKey } from '@tanstack/react-query'
import { keys } from '../api/keys'
import type { CollectionName, WsMessage } from '../api/types'

// Run-event names that change the runs LIST (a run appears / flips finished).
// Mid-run events (act/verify/check) are delivered live to the open RunDetail via
// a direct socket subscription, so they must not thrash the list query.
const RUN_LIST_EVENTS = new Set([
  'mandate_started',
  'flow_started',
  'task_started',
  'mandate_finished',
  'flow_finished',
  'task_finished',
])

const COLLECTION_RESOURCES = new Set<CollectionName>([
  'blueprints',
  'flows',
  'specialists',
  'loops',
  'primers',
])

export function wsInvalidations(msg: WsMessage): QueryKey[] {
  switch (msg.type) {
    case 'project_list_changed':
      return [keys.projects()]
    case 'queue_changed':
      return [keys.queue(msg.project_id)]
    case 'report_added':
      // A run finished and archived: it may have appended a new measurement
      // (metrics), it always changes what an audit window aggregates, and its
      // worktree exit-commit may have just minted a new alc/* demand branch.
      // A finished run also commits the workdir as it goes, so the tree's
      // dirty state may have flipped — re-check it (Loops' run-block gate).
      return [
        keys.queue(msg.project_id),
        keys.scorecard(msg.project_id),
        keys.metrics(msg.project_id),
        keys.audit(msg.project_id),
        keys.branches(msg.project_id),
        keys.worktree(msg.project_id),
      ]
    case 'loop_changed':
      return [
        keys.loopState(msg.project_id, msg.name),
        keys.loopLedger(msg.project_id, msg.name),
        keys.collection(msg.project_id, 'loops'),
        // A loop can be a Team member's pack file — keep the roster live too.
        keys.team(msg.project_id),
      ]
    case 'config_changed': {
      // A manifest change (check_sets) alters the audit AND the onboard proposal
      // (a `project` set that now exists, a stage that was appended) — keep the
      // Checks view live.
      if (msg.resource === 'manifest')
        return [
          keys.manifest(msg.project_id),
          keys.lint(msg.project_id),
          keys.checksAudit(msg.project_id),
          keys.onboardAll(msg.project_id),
          // A config edit is a natural moment to re-check the tree's dirty state
          // (the operator may have just committed/stashed) — keep Loops' run-block honest.
          keys.worktree(msg.project_id),
        ]
      if (msg.resource === 'prompts') return [keys.prompts(msg.project_id)]
      if (COLLECTION_RESOURCES.has(msg.resource as CollectionName)) {
        return [
          keys.collection(msg.project_id, msg.resource as CollectionName),
          keys.lint(msg.project_id),
          // A hire writes into a collection — keep the Team roster live too.
          keys.team(msg.project_id),
          // A blueprint's checks / check_set opt-in changes the audit — keep Checks live.
          keys.checksAudit(msg.project_id),
          // A blueprint's check_set opt-in also changes the onboard proposal
          // (that blueprint drops out of the opt-in candidates) — refresh it.
          keys.onboardAll(msg.project_id),
          // Re-check the tree's dirty state on any collection change — keep
          // Loops' run-block honest as the operator commits/stashes.
          keys.worktree(msg.project_id),
        ]
      }
      return [keys.lint(msg.project_id)]
    }
    case 'run_configs_changed':
      return [keys.runConfigs(msg.project_id)]
    case 'signals_changed':
      return [keys.signals(msg.project_id)]
    case 'worktree_changed':
      // Invalidate-only, on purpose: the WsProvider has ONLY an invalidate
      // pipeline, so we re-fetch /worktree rather than write the pushed `status`
      // into the cache. A setQueryData path would need new machinery AND create a
      // second source of truth (the push vs the endpoint) that could drift; the
      // extra GET is cheap (one debounced request) and keeps one source of truth.
      return [keys.worktree(msg.project_id)]
    case 'run_event':
      return RUN_LIST_EVENTS.has(msg.event.event) ? [keys.runs(msg.project_id)] : []
    case 'exec_output':
      return [keys.execs()]
    case 'exec_finished':
      // An exec (e.g. `explore`) may have just archived new variants and/or
      // minted new alc/* branches — no WS event watches the variants dir
      // directly, so a finished exec is the only live signal for it.
      return [keys.execs(), keys.variants(msg.project_id), keys.branches(msg.project_id)]
    case 'subscribed':
      return []
  }
}
