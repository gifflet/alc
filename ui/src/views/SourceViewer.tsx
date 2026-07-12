// SourceViewer.tsx — Read-only source view for a config file (manifest / unit / prompt).
import { FileWarning } from 'lucide-react'
import { useCollectionItem, useManifest, usePrompt } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import type { CollectionName } from '../api/types'
import type { SourceResource } from '../app/uiStore'
import { CodeView } from '../components/CodeView'
import type { CodeLang } from '../components/CodeView'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/primitives'

const MD_COLLECTIONS = new Set<SourceResource>(['blueprints', 'primers', 'prompts'])

function langFor(resource: SourceResource): CodeLang {
  if (resource === 'manifest') return 'yaml'
  return MD_COLLECTIONS.has(resource) ? 'markdown' : 'yaml'
}

function ManifestSource() {
  const id = useProjectId()
  const { data, isLoading, isError } = useManifest(id)
  if (isLoading) return <Loading />
  if (isError || !data) return <EmptyState icon={FileWarning} message="Could not load manifest." />
  return <CodeView code={data.raw} lang="yaml" />
}

function PromptSource({ name }: { name: string }) {
  const id = useProjectId()
  const { data, isLoading, isError } = usePrompt(id, name)
  if (isLoading) return <Loading />
  if (isError || !data) return <EmptyState icon={FileWarning} message={`Could not load prompt ${name}.`} />
  return <CodeView code={data.raw} lang="markdown" />
}

function CollectionSource({ collection, name }: { collection: CollectionName; name: string }) {
  const id = useProjectId()
  const { data, isLoading, isError } = useCollectionItem(id, collection, name)
  if (isLoading) return <Loading />
  if (isError || !data) return <EmptyState icon={FileWarning} message={`Could not load ${name}.`} />
  return <CodeView code={data.raw} lang={langFor(collection)} />
}

export function SourceViewer({ resource, name }: { resource: SourceResource; name: string }) {
  if (resource === 'manifest') return <ManifestSource />
  if (resource === 'prompts') return <PromptSource name={name} />
  return <CollectionSource collection={resource} name={name} />
}
