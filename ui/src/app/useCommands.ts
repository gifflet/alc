// useCommands.ts — Build the palette's index from the live query cache.
//
// Everything here is already fetched for the views, so opening Cmd+K costs no
// request. Kept out of CommandPalette so the component stays presentational and
// the palette can be rendered in a test with a fixed list.
import { useCollection, useBranches, useQueue, useRuns } from '../api/hooks'
import { useProjectId } from './ProjectContext'
import { openView } from '../components/ActivityBar'
import { sourceTitle } from './tabRoute'
import { uiStore } from './uiStore'
import type { PrimaryView, SourceResource } from './uiStore'
import type { Command } from '../lib/commandIndex'

const VIEWS: Array<[PrimaryView, string]> = [
  ['dashboard', 'Dashboard'],
  ['fleet', 'Fleet'],
  ['inbox', 'Inbox'],
  ['queue', 'Queue'],
  ['runs', 'Runs'],
  ['loops', 'Loops'],
  ['conduct', 'Conduct'],
  ['team', 'Team'],
  ['metrics', 'Metrics'],
  ['compare', 'Compare'],
  ['checks', 'Checks'],
  ['run-configs', 'Run Configurations'],
]

const UNIT_KINDS: Array<[SourceResource, Command['kind']]> = [
  ['blueprints', 'blueprint'],
  ['flows', 'flow'],
  ['specialists', 'specialist'],
  ['loops', 'loop'],
  ['primers', 'primer'],
]

export function useCommands(): Command[] {
  const id = useProjectId()
  const blueprints = useCollection(id, 'blueprints')
  const flows = useCollection(id, 'flows')
  const specialists = useCollection(id, 'specialists')
  const loops = useCollection(id, 'loops')
  const primers = useCollection(id, 'primers')
  const runs = useRuns(id)
  const queue = useQueue(id)
  const branches = useBranches(id)

  const collections: Record<string, Array<{ name: string }>> = {
    blueprints: blueprints.data ?? [],
    flows: flows.data ?? [],
    specialists: specialists.data ?? [],
    loops: loops.data ?? [],
    primers: primers.data ?? [],
  }

  const commands: Command[] = []

  for (const [view, label] of VIEWS) {
    commands.push({ id: `view:${view}`, kind: 'view', label, run: () => openView(view) })
  }

  commands.push({
    id: 'action:manifest',
    kind: 'action',
    label: 'Open manifest',
    hint: 'config',
    run: () =>
      uiStore.openTab({
        target: { type: 'source', resource: 'manifest', name: 'manifest' },
        title: 'manifest.yaml',
      }),
  })

  for (const [resource, kind] of UNIT_KINDS) {
    for (const item of collections[resource]) {
      commands.push({
        id: `${resource}:${item.name}`,
        kind,
        label: item.name,
        hint: sourceTitle(resource, item.name),
        run: () =>
          uiStore.openTab({
            target: { type: 'source', resource, name: item.name },
            title: sourceTitle(resource, item.name),
          }),
      })
    }
  }

  for (const branch of branches.data?.branches ?? []) {
    if (branch.merged) continue // a landed branch is not somewhere to go
    commands.push({
      id: `branch:${branch.name}`,
      kind: 'branch',
      label: branch.name,
      hint: 'review',
      run: () =>
        uiStore.openTab({ target: { type: 'review', branch: branch.name }, title: branch.name }),
    })
  }

  // Runs come pre-sorted newest-first; rankCommands keeps that order on ties.
  for (const run of runs.data?.runs ?? []) {
    commands.push({
      id: `run:${run.stem}`,
      kind: 'run',
      label: run.stem,
      hint: run.kind,
      run: () => uiStore.openTab({ target: { type: 'run', stem: run.stem }, title: run.stem }),
    })
  }

  for (const entry of queue.data?.pending ?? []) {
    // A pending entry wraps the QueueTask; its first line is the human title.
    const title = (entry.task?.task ?? '').split('\n')[0]
    if (!title) continue
    commands.push({
      id: `task:${entry.stem}`,
      kind: 'task',
      label: title,
      hint: 'pending',
      run: () => openView('queue'),
    })
  }

  return commands
}
