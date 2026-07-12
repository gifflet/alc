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
      return [keys.queue(msg.project_id), keys.scorecard(msg.project_id)]
    case 'loop_changed':
      return [
        keys.loopState(msg.project_id, msg.name),
        keys.loopLedger(msg.project_id, msg.name),
        keys.collection(msg.project_id, 'loops'),
      ]
    case 'config_changed': {
      if (msg.resource === 'manifest') return [keys.manifest(msg.project_id), keys.lint(msg.project_id)]
      if (msg.resource === 'prompts') return [keys.prompts(msg.project_id)]
      if (COLLECTION_RESOURCES.has(msg.resource as CollectionName)) {
        return [keys.collection(msg.project_id, msg.resource as CollectionName), keys.lint(msg.project_id)]
      }
      return [keys.lint(msg.project_id)]
    }
    case 'run_configs_changed':
      return [keys.runConfigs(msg.project_id)]
    case 'run_event':
      return RUN_LIST_EVENTS.has(msg.event.event) ? [keys.runs(msg.project_id)] : []
    case 'exec_output':
    case 'exec_finished':
      return [keys.execs()]
    case 'subscribed':
      return []
  }
}
