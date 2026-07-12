// violations.ts — Map a Policy Gate violation to the source file that owns it.
//
// Lint messages name their subject ("Blueprint 'x'…", "Flow 'y'…"); we parse that
// to open the right editor tab from the Problems panel. Pure so it is unit-tested.
import { sourceTitle } from './tabRoute'
import type { OpenTabArg } from './tabRoute'
import type { SourceResource } from './uiStore'
import type { Violation } from '../api/types'

// Ordered: the first match wins, so a blueprint that references a bad prompt
// opens the blueprint (where the fix lives), not the referenced prompt.
const ENTITY_PATTERNS: [RegExp, SourceResource][] = [
  [/Blueprint '([^']+)'/, 'blueprints'],
  [/Flow '([^']+)'/, 'flows'],
  [/Specialist '([^']+)'/, 'specialists'],
  [/Loop '([^']+)'/, 'loops'],
  [/Prompt override '([^']+)'/, 'prompts'],
  [/Prompt '([^']+)'/, 'prompts'],
]

const MANIFEST_RULES = new Set(['default_engine_resolvable', 'compute_tier_maps_engine'])

function sourceArg(resource: SourceResource, name: string): OpenTabArg {
  return { target: { type: 'source', resource, name }, title: sourceTitle(resource, name) }
}

/** The editor tab a violation should open, or null if it names no source. */
export function violationTarget(v: Violation): OpenTabArg | null {
  for (const [re, resource] of ENTITY_PATTERNS) {
    const match = v.message.match(re)
    if (match) return sourceArg(resource, match[1])
  }
  if (MANIFEST_RULES.has(v.rule) || v.message.includes('manifest.')) {
    return sourceArg('manifest', 'manifest')
  }
  return null
}
