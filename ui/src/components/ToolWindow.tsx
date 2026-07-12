// ToolWindow.tsx — Left project tree: collections with counts; leaves open tabs.
import { useState } from 'react'
import { ChevronDown, ChevronRight, FileCode2, FileText } from 'lucide-react'
import { useCollection, usePrompts } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { uiStore, useUiState } from '../app/uiStore'
import type { CollectionName } from '../api/types'
import type { SourceResource } from '../app/uiStore'

interface Leaf {
  name: string
  title: string
}

function TreeSection({
  label,
  resource,
  leaves,
  suffix,
  md,
}: {
  label: string
  resource: SourceResource
  leaves: Leaf[]
  suffix: string
  md: boolean
}) {
  const [open, setOpen] = useState(true)
  const { activeTabId } = useUiState()
  const Chevron = open ? ChevronDown : ChevronRight
  const FileIcon = md ? FileText : FileCode2
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-[28px] w-full items-center gap-1 px-2 text-[12px] text-muted transition-colors duration-120 hover:bg-hover"
      >
        <Chevron className="h-3.5 w-3.5 text-faint" />
        <span className="flex-1 truncate text-left uppercase tracking-wide text-[11px]">
          {label}
        </span>
        <span className="tabular text-[11px] text-faint">{leaves.length}</span>
      </button>
      {open &&
        leaves.map((leaf, i) => {
          const id = `source:${resource}:${leaf.name}`
          return (
            <button
              key={leaf.name}
              type="button"
              onClick={() =>
                uiStore.openTab({
                  target: { type: 'source', resource, name: leaf.name },
                  title: `${leaf.name}${suffix}`,
                })
              }
              style={{ animationDelay: `${Math.min(i, 8) * 12}ms` }}
              className={`alc-fade-in flex h-[28px] w-full items-center gap-1.5 pl-7 pr-2 text-[12px] transition-colors duration-120 ${
                activeTabId === id ? 'bg-hover text-primary' : 'text-muted hover:bg-hover'
              }`}
            >
              <FileIcon className="h-3.5 w-3.5 shrink-0 text-faint" />
              <span className="truncate">{leaf.name}</span>
            </button>
          )
        })}
    </div>
  )
}

function CollectionSection({
  label,
  collection,
  suffix,
  md,
}: {
  label: string
  collection: CollectionName
  suffix: string
  md: boolean
}) {
  const id = useProjectId()
  const { data } = useCollection(id, collection)
  const leaves = (data ?? []).map((it) => ({ name: it.name, title: it.name }))
  return (
    <TreeSection label={label} resource={collection} leaves={leaves} suffix={suffix} md={md} />
  )
}

function PromptsSection() {
  const id = useProjectId()
  const { data } = usePrompts(id)
  const leaves = (data ?? []).map((p) => ({ name: p.name, title: p.name }))
  return <TreeSection label="Prompts" resource="prompts" leaves={leaves} suffix=".md" md />
}

export function ToolWindow() {
  return (
    <div className="flex h-full flex-col overflow-y-auto bg-panel">
      <button
        type="button"
        onClick={() =>
          uiStore.openTab({
            target: { type: 'source', resource: 'manifest', name: 'manifest' },
            title: 'manifest.yaml',
          })
        }
        className="flex h-[28px] w-full items-center gap-1.5 px-2 text-[12px] text-muted transition-colors duration-120 hover:bg-hover"
      >
        <FileCode2 className="h-3.5 w-3.5 shrink-0 text-faint" />
        <span className="truncate">manifest.yaml</span>
      </button>
      <CollectionSection label="Blueprints" collection="blueprints" suffix=".md" md />
      <CollectionSection label="Flows" collection="flows" suffix=".yaml" md={false} />
      <CollectionSection label="Specialists" collection="specialists" suffix=".yaml" md={false} />
      <CollectionSection label="Loops" collection="loops" suffix=".yaml" md={false} />
      <CollectionSection label="Primers" collection="primers" suffix=".md" md />
      <PromptsSection />
    </div>
  )
}
