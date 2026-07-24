// keys.ts — Canonical TanStack Query keys. Prefix-matched by invalidateQueries.
import type { CollectionName } from './types'

export const keys = {
  projects: () => ['projects'] as const,
  execs: () => ['execs'] as const,
  commands: () => ['commands'] as const,
  runConfigs: (id: string) => ['project', id, 'run-configs'] as const,
  manifest: (id: string) => ['project', id, 'manifest'] as const,
  // The shared prefix over every per-collection key — invalidating it (partial
  // match) refreshes every collection at once, e.g. after a Team hire writes
  // across blueprints/flows/specialists/loops in one go.
  collections: (id: string) => ['project', id, 'collection'] as const,
  collection: (id: string, c: CollectionName) => ['project', id, 'collection', c] as const,
  collectionItem: (id: string, c: CollectionName, name: string) =>
    ['project', id, 'collection', c, name] as const,
  prompts: (id: string) => ['project', id, 'prompts'] as const,
  prompt: (id: string, name: string) => ['project', id, 'prompt', name] as const,
  queue: (id: string) => ['project', id, 'queue'] as const,
  branches: (id: string) => ['project', id, 'branches'] as const,
  variants: (id: string) => ['project', id, 'variants'] as const,
  signals: (id: string) => ['project', id, 'signals'] as const,
  runs: (id: string) => ['project', id, 'runs'] as const,
  run: (id: string, stem: string) => ['project', id, 'run', stem] as const,
  loopState: (id: string, name: string) => ['project', id, 'loop', name, 'state'] as const,
  loopLedger: (id: string, name: string) => ['project', id, 'loop', name, 'ledger'] as const,
  lint: (id: string) => ['project', id, 'lint'] as const,
  engines: (id: string) => ['project', id, 'engines'] as const,
  scorecard: (id: string) => ['project', id, 'scorecard'] as const,
  team: (id: string) => ['project', id, 'team'] as const,
  metrics: (id: string) => ['project', id, 'metrics'] as const,
  runArtifacts: (id: string, stem: string) => ['project', id, 'run-artifacts', stem] as const,
  // The shared prefix over every windowed audit query — invalidating it
  // (partial match) refreshes whichever window(s) a client has open.
  audit: (id: string) => ['project', id, 'audit'] as const,
  auditWindow: (id: string, since: string) => ['project', id, 'audit', since] as const,
}
