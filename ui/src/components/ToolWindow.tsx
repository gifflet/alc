// ToolWindow.tsx — Left project tree: collections with counts + create/delete.
//
// Each section has a "+" to scaffold a new unit (the server fills a minimal valid
// template) and a hover delete on every leaf. Reserved prompts that have not been
// ejected offer "Eject" instead of delete, since they resolve to a built-in default.
import { useState } from 'react'
import type { ReactNode } from 'react'
import {
  ChevronDown,
  ChevronRight,
  FileCode2,
  FileText,
  FileUp,
  Play,
  Plus,
  Repeat,
  Trash2,
} from 'lucide-react'
import { ApiError } from '../api/client'
import {
  useCollection,
  useCreateCollectionItem,
  useCreatePrompt,
  useDeleteCollectionItem,
  useDeletePrompt,
  useEjectPrompt,
  usePrompts,
} from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { tabId, uiStore, useUiState } from '../app/uiStore'
import type { CollectionName, PromptEntry } from '../api/types'
import { LoopRunDialog } from '../views/LoopRunDialog'
import { RunDialog } from '../views/RunDialog'
import type { RunCommand } from '../views/RunDialog'
import { ConfirmDialog, Dialog, DialogButton } from './Dialog'
import { TextInput } from './fields'

function SectionShell({
  label,
  count,
  onCreate,
  children,
}: {
  label: string
  count: number
  onCreate: () => void
  children: ReactNode
}) {
  const [open, setOpen] = useState(true)
  const Chevron = open ? ChevronDown : ChevronRight
  return (
    <div>
      <div className="group/section flex h-[28px] w-full items-center gap-1 px-2 text-[12px] text-muted transition-colors duration-120 hover:bg-hover">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex flex-1 items-center gap-1 truncate text-left"
        >
          <Chevron className="h-3.5 w-3.5 text-faint" />
          <span className="flex-1 truncate uppercase tracking-wide text-[11px]">{label}</span>
        </button>
        <span className="tabular text-[11px] text-faint">{count}</span>
        <button
          type="button"
          aria-label={`New ${label}`}
          onClick={onCreate}
          className="flex h-4 w-4 items-center justify-center text-faint opacity-0 transition-opacity duration-120 hover:text-primary group-hover/section:opacity-100"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
      {open && children}
    </div>
  )
}

function LeafRow({
  icon: Icon,
  name,
  active,
  onOpen,
  action,
  index,
}: {
  icon: typeof FileText
  name: string
  active: boolean
  onOpen: () => void
  action: ReactNode
  index: number
}) {
  return (
    <div
      style={{ animationDelay: `${Math.min(index, 8) * 12}ms` }}
      className={`group/leaf alc-fade-in flex h-[28px] w-full items-center gap-1.5 pl-7 pr-2 text-[12px] transition-colors duration-120 ${
        active ? 'bg-hover text-primary' : 'text-muted hover:bg-hover'
      }`}
    >
      <button type="button" onClick={onOpen} className="flex min-w-0 flex-1 items-center gap-1.5">
        <Icon className="h-3.5 w-3.5 shrink-0 text-faint" />
        <span className="truncate">{name}</span>
      </button>
      <span className="opacity-0 transition-opacity duration-120 group-hover/leaf:opacity-100">
        {action}
      </span>
    </div>
  )
}

function NewFileDialog({
  label,
  onSubmit,
  onClose,
  error,
  pending,
}: {
  label: string
  onSubmit: (name: string) => void
  onClose: () => void
  error: string | null
  pending: boolean
}) {
  const [name, setName] = useState('')
  const clean = name.trim()
  return (
    <Dialog
      title={`New ${label}`}
      onClose={onClose}
      footer={
        <>
          <DialogButton tone="ghost" onClick={onClose}>
            Cancel
          </DialogButton>
          <DialogButton onClick={() => clean && onSubmit(clean)} disabled={!clean || pending}>
            Create
          </DialogButton>
        </>
      }
    >
      <div className="flex flex-col gap-2">
        <TextInput value={name} onChange={setName} placeholder="name" mono autoFocus />
        <p className="text-[11px] text-faint">A minimal valid template is scaffolded for you.</p>
        {error && <p className="text-[11px] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}

function apiMessage(error: unknown): string | null {
  if (error instanceof ApiError) return error.message
  return error ? 'Request failed.' : null
}

function CollectionSection({
  label,
  collection,
  suffix,
  md,
  runCommand,
  loop,
}: {
  label: string
  collection: CollectionName
  suffix: string
  md: boolean
  runCommand?: RunCommand
  loop?: boolean
}) {
  const id = useProjectId()
  const start = useStartExec()
  const { activeTabId } = useUiState()
  const { data } = useCollection(id, collection)
  const create = useCreateCollectionItem(id, collection)
  const del = useDeleteCollectionItem(id, collection)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [running, setRunning] = useState<string | null>(null)
  const FileIcon = md ? FileText : FileCode2
  const leaves = data ?? []

  const openTab = (name: string) =>
    uiStore.openTab({
      target: { type: 'source', resource: collection, name },
      title: `${name}${suffix}`,
    })

  const submitCreate = (name: string) =>
    create.mutate(name, {
      onSuccess: () => {
        setCreating(false)
        create.reset()
        openTab(name)
      },
    })

  const confirmDelete = () => {
    if (!deleting) return
    del.mutate(deleting, {
      onSuccess: () => {
        uiStore.closeTab(tabId({ type: 'source', resource: collection, name: deleting }))
        setDeleting(null)
      },
    })
  }

  return (
    <SectionShell label={label} count={leaves.length} onCreate={() => setCreating(true)}>
      {leaves.map((leaf, i) => {
        const id2 = tabId({ type: 'source', resource: collection, name: leaf.name })
        return (
          <LeafRow
            key={leaf.name}
            icon={FileIcon}
            name={leaf.name}
            index={i}
            active={activeTabId === id2}
            onOpen={() => openTab(leaf.name)}
            action={
              <span className="flex items-center gap-1">
                {runCommand && (
                  <button
                    type="button"
                    aria-label={`Run ${leaf.name}`}
                    onClick={() => setRunning(leaf.name)}
                    className="flex h-4 w-4 items-center justify-center text-faint hover:text-live"
                  >
                    <Play className="h-3.5 w-3.5" />
                  </button>
                )}
                {loop && (
                  <>
                    <button
                      type="button"
                      aria-label={`Run cycle ${leaf.name}`}
                      onClick={() => void start('cycle', { name: leaf.name }).catch(() => {})}
                      className="flex h-4 w-4 items-center justify-center text-faint hover:text-live"
                    >
                      <Play className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      aria-label={`Run loop ${leaf.name}`}
                      onClick={() => setRunning(leaf.name)}
                      className="flex h-4 w-4 items-center justify-center text-faint hover:text-live"
                    >
                      <Repeat className="h-3.5 w-3.5" />
                    </button>
                  </>
                )}
                <button
                  type="button"
                  aria-label={`Delete ${leaf.name}`}
                  onClick={() => setDeleting(leaf.name)}
                  className="flex h-4 w-4 items-center justify-center text-faint hover:text-error"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </span>
            }
          />
        )
      })}
      {running && runCommand && (
        <RunDialog command={runCommand} name={running} onClose={() => setRunning(null)} />
      )}
      {running && loop && <LoopRunDialog name={running} onClose={() => setRunning(null)} />}
      {creating && (
        <NewFileDialog
          label={label.replace(/s$/, '')}
          onSubmit={submitCreate}
          onClose={() => {
            setCreating(false)
            create.reset()
          }}
          error={apiMessage(create.error)}
          pending={create.isPending}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={`Delete ${deleting}?`}
          message={`This removes ${deleting}${suffix} from the project.`}
          confirmLabel="Delete"
          onConfirm={confirmDelete}
          onCancel={() => setDeleting(null)}
        />
      )}
    </SectionShell>
  )
}

function PromptsSection() {
  const id = useProjectId()
  const { activeTabId } = useUiState()
  const { data } = usePrompts(id)
  const create = useCreatePrompt(id)
  const del = useDeletePrompt(id)
  const eject = useEjectPrompt(id)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)
  const leaves = data ?? []

  const openTab = (name: string) =>
    uiStore.openTab({ target: { type: 'source', resource: 'prompts', name }, title: `${name}.md` })

  const submitCreate = (name: string) =>
    create.mutate(name, {
      onSuccess: () => {
        setCreating(false)
        create.reset()
        openTab(name)
      },
    })

  const confirmDelete = () => {
    if (!deleting) return
    del.mutate(deleting, {
      onSuccess: () => {
        uiStore.closeTab(tabId({ type: 'source', resource: 'prompts', name: deleting }))
        setDeleting(null)
      },
    })
  }

  const leafAction = (p: PromptEntry): ReactNode => {
    if (p.reserved && !p.ejected) {
      return (
        <button
          type="button"
          aria-label={`Eject ${p.name}`}
          title="Eject default to override"
          onClick={() => eject.mutate(p.name, { onSuccess: () => openTab(p.name) })}
          className="flex h-4 w-4 items-center justify-center text-faint hover:text-accent"
        >
          <FileUp className="h-3.5 w-3.5" />
        </button>
      )
    }
    return (
      <button
        type="button"
        aria-label={`Delete ${p.name}`}
        onClick={() => setDeleting(p.name)}
        className="flex h-4 w-4 items-center justify-center text-faint hover:text-error"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    )
  }

  return (
    <SectionShell label="Prompts" count={leaves.length} onCreate={() => setCreating(true)}>
      {leaves.map((p, i) => (
        <LeafRow
          key={p.name}
          icon={FileText}
          name={p.name}
          index={i}
          active={activeTabId === tabId({ type: 'source', resource: 'prompts', name: p.name })}
          onOpen={() => openTab(p.name)}
          action={leafAction(p)}
        />
      ))}
      {creating && (
        <NewFileDialog
          label="Prompt"
          onSubmit={submitCreate}
          onClose={() => {
            setCreating(false)
            create.reset()
          }}
          error={apiMessage(create.error)}
          pending={create.isPending}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={`Delete ${deleting}?`}
          message={`This removes the ${deleting}.md prompt override.`}
          confirmLabel="Delete"
          onConfirm={confirmDelete}
          onCancel={() => setDeleting(null)}
        />
      )}
    </SectionShell>
  )
}

export function ToolWindow() {
  const { activeTabId } = useUiState()
  const manifestActive =
    activeTabId === tabId({ type: 'source', resource: 'manifest', name: 'manifest' })
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
        className={`flex h-[28px] w-full items-center gap-1.5 px-2 text-[12px] transition-colors duration-120 hover:bg-hover ${
          manifestActive ? 'bg-hover text-primary' : 'text-muted'
        }`}
      >
        <FileCode2 className="h-3.5 w-3.5 shrink-0 text-faint" />
        <span className="truncate">manifest.yaml</span>
      </button>
      <CollectionSection label="Blueprints" collection="blueprints" suffix=".md" md runCommand="run" />
      <CollectionSection label="Flows" collection="flows" suffix=".yaml" md={false} runCommand="flow" />
      <CollectionSection
        label="Specialists"
        collection="specialists"
        suffix=".yaml"
        md={false}
        runCommand="specialist"
      />
      <CollectionSection label="Loops" collection="loops" suffix=".yaml" md={false} loop />
      <CollectionSection label="Primers" collection="primers" suffix=".md" md />
      <PromptsSection />
    </div>
  )
}
