// hooks.ts — TanStack Query hooks over the typed API client.
//
// Read-only for Phase 2: every hook is a useQuery. Live freshness comes from WS
// invalidation (see WsProvider), so staleTime can be generous and there is no
// polling. Run detail is the one exception — it tails incrementally in its view.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { keys } from './keys'
import type { CollectionName, QueueTask } from './types'

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
    // Engine health is probed live, so re-check on a slow cadence (and on WS
    // reconnect, see WsProvider) to keep the status dots honest.
    refetchInterval: 60_000,
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

// ---------------------------------------------------------------------------
// Mutations — Phase 3. WS invalidation keeps other clients fresh; each mutation
// also invalidates directly so the acting client updates without waiting on WS.
// ---------------------------------------------------------------------------

export function useSaveManifest(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (raw: string) => api.putManifest(id, raw),
    onSuccess: (data) => {
      qc.setQueryData(keys.manifest(id), data)
      qc.invalidateQueries({ queryKey: keys.lint(id) })
      qc.invalidateQueries({ queryKey: keys.engines(id) })
    },
  })
}

export function useSaveCollectionItem(id: string, collection: CollectionName, name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (raw: string) => api.putCollectionItem(id, collection, name, raw),
    onSuccess: (data) => {
      qc.setQueryData(keys.collectionItem(id, collection, name), data)
      qc.invalidateQueries({ queryKey: keys.collection(id, collection) })
      qc.invalidateQueries({ queryKey: keys.lint(id) })
    },
  })
}

export function useCreateCollectionItem(id: string, collection: CollectionName) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.createCollectionItem(id, collection, name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.collection(id, collection) })
      qc.invalidateQueries({ queryKey: keys.lint(id) })
    },
  })
}

export function useDeleteCollectionItem(id: string, collection: CollectionName) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.deleteCollectionItem(id, collection, name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.collection(id, collection) })
      qc.invalidateQueries({ queryKey: keys.lint(id) })
    },
  })
}

export function useSavePrompt(id: string, name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (raw: string) => api.putPrompt(id, name, raw),
    onSuccess: (data) => {
      qc.setQueryData(keys.prompt(id, name), data)
      qc.invalidateQueries({ queryKey: keys.prompts(id) })
    },
  })
}

export function useCreatePrompt(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.createPrompt(id, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.prompts(id) }),
  })
}

export function useDeletePrompt(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.deletePrompt(id, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.prompts(id) }),
  })
}

/** Eject a reserved prompt: materialise its resolved default as an override file. */
export function useEjectPrompt(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (name: string) => {
      const current = await api.getPrompt(id, name)
      return api.putPrompt(id, name, current.raw)
    },
    onSuccess: (data, name) => {
      qc.setQueryData(keys.prompt(id, name), data)
      qc.invalidateQueries({ queryKey: keys.prompts(id) })
    },
  })
}

export function useEnqueueTask(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (task: Partial<QueueTask>) => api.enqueueTask(id, task),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.queue(id) }),
  })
}

export function useDeletePending(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (stem: string) => api.deletePending(id, stem),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.queue(id) }),
  })
}

export function useRetryQueue(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { stem?: string; all?: boolean }) => api.retryQueue(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.queue(id) }),
  })
}
