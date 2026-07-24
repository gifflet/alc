// tabRoute.ts — Two-way mapping between a tab target and its project URL.
//
// The router owns only the project scope (/projects/:id); the active tab is
// reflected in the path suffix so a deep-link or a refresh reopens exactly that
// tab. Pure functions so the mapping is unit-tested without React or the router.
import type { PrimaryView, SourceResource, TabTarget } from './uiStore'

/** The argument shape uiStore.openTab expects. */
export interface OpenTabArg {
  target: TabTarget
  title: string
  closable?: boolean
}

const VIEW_TITLE: Record<PrimaryView, string> = {
  dashboard: 'Dashboard',
  queue: 'Queue',
  runs: 'Runs',
  loops: 'Loops',
  conduct: 'Conduct',
  'run-configs': 'Run Configurations',
  team: 'Team',
  metrics: 'Metrics',
  compare: 'Compare',
  checks: 'Checks',
}

const PRIMARY_VIEWS = new Set<PrimaryView>([
  'dashboard',
  'queue',
  'runs',
  'loops',
  'conduct',
  'run-configs',
  'team',
  'metrics',
  'compare',
  'checks',
])

/** File-extension suffixes per config resource (mirrors the tool window). */
const SOURCE_SUFFIX: Record<SourceResource, string> = {
  manifest: '.yaml',
  blueprints: '.md',
  flows: '.yaml',
  specialists: '.yaml',
  loops: '.yaml',
  primers: '.md',
  prompts: '.md',
}

/** The tab title for a config source (e.g. "chore.md", "manifest.yaml"). */
export function sourceTitle(resource: SourceResource, name: string): string {
  return `${name}${SOURCE_SUFFIX[resource]}`
}

/** The project-relative URL that reflects a given tab. */
export function pathForTab(id: string, target: TabTarget): string {
  const base = `/projects/${id}`
  switch (target.type) {
    case 'view':
      // Dashboard is the project home — keep its URL bare.
      return target.view === 'dashboard' ? base : `${base}/${target.view}`
    case 'run':
      return `${base}/runs/${encodeURIComponent(target.stem)}`
    case 'loop':
      return `${base}/loops/${encodeURIComponent(target.name)}`
    case 'source':
      return target.resource === 'manifest'
        ? `${base}/config/manifest`
        : `${base}/config/${target.resource}/${encodeURIComponent(target.name)}`
  }
}

function viewArg(view: PrimaryView): OpenTabArg {
  return { target: { type: 'view', view }, title: VIEW_TITLE[view], closable: false }
}

function sourceArg(resource: SourceResource, name: string): OpenTabArg {
  return { target: { type: 'source', resource, name }, title: sourceTitle(resource, name) }
}

/** Config resources reachable through /config/… (loops here is the yaml file). */
const SOURCE_RESOURCES = new Set<SourceResource>([
  'blueprints',
  'flows',
  'specialists',
  'loops',
  'primers',
  'prompts',
])

/** Parse a project-relative path (its non-empty segments) into an openTab arg. */
export function openArgFromPath(segments: string[]): OpenTabArg | null {
  if (segments.length === 0) return viewArg('dashboard')
  const [head, ...rest] = segments

  if (rest.length === 0 && PRIMARY_VIEWS.has(head as PrimaryView)) {
    return viewArg(head as PrimaryView)
  }
  if (head === 'runs' && rest.length === 1) {
    return { target: { type: 'run', stem: decodeURIComponent(rest[0]) }, title: decodeURIComponent(rest[0]) }
  }
  if (head === 'loops' && rest.length === 1) {
    return { target: { type: 'loop', name: decodeURIComponent(rest[0]) }, title: decodeURIComponent(rest[0]) }
  }
  if (head === 'config') {
    if (rest.length === 1 && rest[0] === 'manifest') return sourceArg('manifest', 'manifest')
    if (rest.length === 2 && SOURCE_RESOURCES.has(rest[0] as SourceResource)) {
      return sourceArg(rest[0] as SourceResource, decodeURIComponent(rest[1]))
    }
  }
  return null
}
