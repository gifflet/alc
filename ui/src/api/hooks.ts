// hooks.ts — TanStack Query hooks over the typed API client.
//
// Read-only for Phase 2: every hook is a useQuery. Live freshness comes from WS
// invalidation (see WsProvider), so staleTime can be generous and there is no
// polling. Run detail is the one exception — it tails incrementally in its view.
import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import { keys } from './keys'
import type { CollectionName } from './types'

const enabled = (id: string | undefined): boolean => Boolean(id)

export function useProjects() {
  return useQuery({ queryKey: keys.projects(), queryFn: api.listProjects })
}

export function useManifest(id: string) {
  return useQuery({
    queryKey: keys.manifest(id),
    queryFn: () => api.getManifest(id),
    enabled: enabled(id),
  })
}

export function useCollection(id: string, collection: CollectionName) {
  return useQuery({
    queryKey: keys.collection(id, collection),
    queryFn: () => api.listCollection(id, collection),
    enabled: enabled(id),
  })
}

export function useCollectionItem(id: string, collection: CollectionName, name: string) {
  return useQuery({
    queryKey: keys.collectionItem(id, collection, name),
    queryFn: () => api.getCollectionItem(id, collection, name),
    enabled: enabled(id) && Boolean(name),
  })
}

export function usePrompts(id: string) {
  return useQuery({
    queryKey: keys.prompts(id),
    queryFn: () => api.listPrompts(id),
    enabled: enabled(id),
  })
}

export function usePrompt(id: string, name: string) {
  return useQuery({
    queryKey: keys.prompt(id, name),
    queryFn: () => api.getPrompt(id, name),
    enabled: enabled(id) && Boolean(name),
  })
}

export function useQueue(id: string) {
  return useQuery({ queryKey: keys.queue(id), queryFn: () => api.getQueue(id), enabled: enabled(id) })
}

export function useRuns(id: string) {
  return useQuery({ queryKey: keys.runs(id), queryFn: () => api.listRuns(id), enabled: enabled(id) })
}

export function useLoopState(id: string, name: string) {
  return useQuery({
    queryKey: keys.loopState(id, name),
    queryFn: () => api.getLoopState(id, name),
    enabled: enabled(id) && Boolean(name),
  })
}

export function useLoopLedger(id: string, name: string) {
  return useQuery({
    queryKey: keys.loopLedger(id, name),
    queryFn: () => api.getLoopLedger(id, name),
    enabled: enabled(id) && Boolean(name),
  })
}

export function useLint(id: string) {
  return useQuery({ queryKey: keys.lint(id), queryFn: () => api.getLint(id), enabled: enabled(id) })
}

export function useEngines(id: string) {
  return useQuery({
    queryKey: keys.engines(id),
    queryFn: () => api.getEngines(id),
    enabled: enabled(id),
  })
}

export function useScorecard(id: string) {
  return useQuery({
    queryKey: keys.scorecard(id),
    queryFn: () => api.getScorecard(id),
    enabled: enabled(id),
  })
}

export function useExecs() {
  return useQuery({ queryKey: keys.execs(), queryFn: api.listExecs })
}
