// keys.ts — Canonical TanStack Query keys. Prefix-matched by invalidateQueries.
import type { CollectionName } from './types'

export const keys = {
  projects: () => ['projects'] as const,
  execs: () => ['execs'] as const,
  manifest: (id: string) => ['project', id, 'manifest'] as const,
  collection: (id: string, c: CollectionName) => ['project', id, 'collection', c] as const,
  collectionItem: (id: string, c: CollectionName, name: string) =>
    ['project', id, 'collection', c, name] as const,
  prompts: (id: string) => ['project', id, 'prompts'] as const,
  prompt: (id: string, name: string) => ['project', id, 'prompt', name] as const,
  queue: (id: string) => ['project', id, 'queue'] as const,
  runs: (id: string) => ['project', id, 'runs'] as const,
  run: (id: string, stem: string) => ['project', id, 'run', stem] as const,
  loopState: (id: string, name: string) => ['project', id, 'loop', name, 'state'] as const,
  loopLedger: (id: string, name: string) => ['project', id, 'loop', name, 'ledger'] as const,
  lint: (id: string) => ['project', id, 'lint'] as const,
  engines: (id: string) => ['project', id, 'engines'] as const,
  scorecard: (id: string) => ['project', id, 'scorecard'] as const,
}
