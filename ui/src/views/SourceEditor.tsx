// SourceEditor.tsx — Editable source + structured form for a config file.
//
// Replaces the read-only viewer: Monaco (lazy-loaded so it stays out of the main
// bundle) backs the Source view, with CodeView as the instant-highlight fallback
// while the editor chunk loads. Manifest and blueprints also get a structured
// Form view. Dirty state drives the tab dot + close guard; the server validates
// every save and 422 details render in a panel below the editor.
import { Suspense, lazy, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { AlertTriangle, Check, FileWarning, Lock, Play, RotateCcw, Save } from 'lucide-react'
import { ApiError } from '../api/client'
import {
  useCollection,
  useCollectionItem,
  useManifest,
  usePrompt,
  useSaveCollectionItem,
  useSaveManifest,
  useSavePrompt,
} from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { tabId } from '../app/uiStore'
import { uiStore } from '../app/uiStore'
import type { SourceResource } from '../app/uiStore'
import { getDraft, setDraft as cacheDraft } from '../lib/draftCache'
import type { CollectionName } from '../api/types'
import { CodeView } from '../components/CodeView'
import { useNarrow } from '../app/useDensity'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/primitives'
import { RunDialog } from './RunDialog'
import type { RunCommand } from './RunDialog'
import { ActionButton } from '../components/ActionButton'

// Collections the IDE can launch straight from the editor toolbar.
const RUN_COMMANDS: Partial<Record<CollectionName, RunCommand>> = {
  blueprints: 'run',
  flows: 'flow',
  specialists: 'specialist',
}

// Lazy so neither Monaco nor the `yaml` round-trip library (used by the forms)
// lands in the initial bundle — both load on first edit / form toggle.
const CodeEditor = lazy(() => import('../components/CodeEditor'))
const ManifestForm = lazy(() =>
  import('./forms/ManifestForm').then((m) => ({ default: m.ManifestForm })),
)
const BlueprintForm = lazy(() =>
  import('./forms/BlueprintForm').then((m) => ({ default: m.BlueprintForm })),
)
const FlowForm = lazy(() => import('./forms/FlowForm').then((m) => ({ default: m.FlowForm })))
const LoopForm = lazy(() => import('./forms/LoopForm').then((m) => ({ default: m.LoopForm })))
const SpecialistForm = lazy(() =>
  import('./forms/SpecialistForm').then((m) => ({ default: m.SpecialistForm })),
)
const PrimerForm = lazy(() => import('./forms/PrimerForm').then((m) => ({ default: m.PrimerForm })))

const MD_RESOURCES = new Set<SourceResource>(['blueprints', 'primers', 'prompts'])

function langFor(resource: SourceResource): 'yaml' | 'markdown' {
  return MD_RESOURCES.has(resource) ? 'markdown' : 'yaml'
}

interface SaveLike {
  mutateAsync: (raw: string) => Promise<{ raw: string }>
  isPending: boolean
}

function EditorShell({
  id,
  serverRaw,
  isLoading,
  isError,
  language,
  readOnly = false,
  readOnlyNote,
  save,
  renderForm,
  headerExtra,
}: {
  id: string
  serverRaw: string | undefined
  isLoading: boolean
  isError: boolean
  language: 'yaml' | 'markdown'
  readOnly?: boolean
  readOnlyNote?: string
  save?: SaveLike
  renderForm?: (value: string, onChange: (v: string) => void) => ReactNode
  headerExtra?: ReactNode
}) {
  const narrow = useNarrow()
  // Seed from the per-tab cache so edits survive switching away and back.
  const cached = getDraft(id)
  const [draft, setDraftState] = useState(cached?.draft ?? '')
  const [baseline, setBaseline] = useState<string | null>(cached?.baseline ?? null)
  const [mode, setMode] = useState<'source' | 'form'>('source')
  const [error, setError] = useState<ApiError | null>(null)
  const [saved, setSaved] = useState(false)

  const commit = (nextDraft: string, nextBaseline: string) => {
    setDraftState(nextDraft)
    setBaseline(nextBaseline)
    cacheDraft(id, { draft: nextDraft, baseline: nextBaseline })
  }

  // Adopt server content on first load and whenever there are no pending edits.
  useEffect(() => {
    if (serverRaw === undefined) return
    if (baseline === null || draft === baseline) commit(serverRaw, serverRaw)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverRaw])

  const dirty = baseline !== null && draft !== baseline

  useEffect(() => {
    uiStore.setDirty(id, dirty)
  }, [id, dirty])

  if (isLoading) return <Loading />
  if (isError || serverRaw === undefined) {
    return <EmptyState icon={FileWarning} message="Could not load this file." />
  }

  const onChange = (v: string) => {
    setDraftState(v)
    cacheDraft(id, { draft: v, baseline: baseline ?? v })
    setSaved(false)
  }

  const doSave = async () => {
    if (readOnly || !save || !dirty) return
    setError(null)
    try {
      const data = await save.mutateAsync(draft)
      commit(data.raw, data.raw)
      setSaved(true)
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError('Save failed.', 0, null))
    }
  }

  const revert = () => {
    if (baseline !== null) commit(baseline, baseline)
    setError(null)
  }

  const onKeyDownCapture = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S')) {
      e.preventDefault()
      void doSave()
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col" onKeyDownCapture={onKeyDownCapture}>
      <div className="flex min-h-8 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-panel px-2">
        <div className="flex items-center gap-2">
          {renderForm && (
            <div className="flex overflow-hidden rounded-panel border border-border">
              {(['form', 'source'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={`min-h-[var(--ui-control-h)] px-2 text-[length:var(--ui-text-label)] capitalize transition-colors duration-120 ${
                    mode === m ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-hover'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          )}
          {headerExtra}
        </div>
        <div className="flex items-center gap-2">
          {readOnly ? (
            <span className="flex items-center gap-1 text-[length:var(--ui-text-label)] text-faint">
              <Lock className="h-3 w-3" />
              {readOnlyNote ?? 'read-only'}
            </span>
          ) : (
            <>
              {saved && !dirty && (
                <span className="flex items-center gap-1 text-[length:var(--ui-text-label)] text-live">
                  <Check className="h-3 w-3" />
                  saved
                </span>
              )}
              {dirty && <span className="text-[length:var(--ui-text-label)] text-warn">unsaved</span>}
              <ActionButton
                onClick={revert}
                disabled={!dirty}
                tone="ghost"
                size="sm"
              >
                <RotateCcw className="h-3 w-3" />
                Revert
              </ActionButton>
              <ActionButton
                onClick={() => void doSave()}
                disabled={!dirty || save?.isPending}
                tone="accent"
                size="sm"
              >
                <Save className="h-3 w-3" />
                Save
              </ActionButton>
            </>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {mode === 'form' && renderForm ? (
          <Suspense fallback={<Loading />}>{renderForm(draft, onChange)}</Suspense>
        ) : narrow ? (
          // Monaco is a ~2 MB chunk built for a mouse, and it overflows its own
          // container on a phone (measured on device). A phone is for deciding,
          // not editing: show the read-only viewer and never fetch the editor.
          <CodeView code={draft} lang={language} />
        ) : (
          <Suspense fallback={<CodeView code={draft} lang={language} />}>
            <CodeEditor value={draft} language={language} readOnly={readOnly} onChange={onChange} />
          </Suspense>
        )}
      </div>

      {error && <ErrorPanel error={error} />}
    </div>
  )
}

function ErrorPanel({ error }: { error: ApiError }) {
  return (
    <div className="max-h-32 shrink-0 overflow-auto border-t border-error/40 bg-error/10 px-3 py-2 text-[length:var(--ui-text-body)]">
      <div className="flex items-center gap-1.5 font-medium text-error">
        <AlertTriangle className="h-3.5 w-3.5" />
        {error.message}
      </div>
      {error.violations.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 font-mono text-[length:var(--ui-text-label)] text-error/90">
          {error.violations.map((v, i) => (
            <li key={i}>
              <span className="text-faint">{v.rule}:</span> {v.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Resource-specific wiring (one hook set each, then the shared shell)
// ---------------------------------------------------------------------------

function ManifestEditor() {
  const id = useProjectId()
  const { data, isLoading, isError } = useManifest(id)
  const save = useSaveManifest(id)
  return (
    <EditorShell
      id={tabId({ type: 'source', resource: 'manifest', name: 'manifest' })}
      serverRaw={data?.raw}
      isLoading={isLoading}
      isError={isError}
      language="yaml"
      save={save}
      renderForm={(value, onChange) => <ManifestForm value={value} onChange={onChange} />}
    />
  )
}

function PromptEditor({ name }: { name: string }) {
  const id = useProjectId()
  const { data, isLoading, isError } = usePrompt(id, name)
  const save = useSavePrompt(id, name)
  // A reserved prompt that has not been ejected resolves to its built-in default;
  // editing it in place would be a lie — eject it from the tree first.
  const readOnly = Boolean(data?.reserved && !data?.ejected)
  return (
    <EditorShell
      id={tabId({ type: 'source', resource: 'prompts', name })}
      serverRaw={data?.raw}
      isLoading={isLoading}
      isError={isError}
      language="markdown"
      readOnly={readOnly}
      readOnlyNote={readOnly ? 'reserved default — eject to edit' : undefined}
      save={save}
    />
  )
}

function CollectionEditor({ collection, name }: { collection: CollectionName; name: string }) {
  const id = useProjectId()
  const { data, isLoading, isError } = useCollectionItem(id, collection, name)
  const manifest = useManifest(id)
  // Feeds SpecialistForm's blueprint Select; harmless to fetch for every other
  // collection too — the same query other panels (e.g. ExploreDialog) already
  // keep warm, so this is a cache hit more often than not.
  const blueprints = useCollection(id, 'blueprints')
  const save = useSaveCollectionItem(id, collection, name)
  const [running, setRunning] = useState(false)

  const parsed = manifest.data?.parsed as
    | { compute_tiers?: Record<string, unknown>; check_sets?: Record<string, unknown> }
    | undefined
  const tiers = parsed?.compute_tiers ? Object.keys(parsed.compute_tiers) : []
  const checkSets = parsed?.check_sets ? Object.keys(parsed.check_sets) : []
  const blueprintNames = (blueprints.data ?? []).map((b) => b.name)

  const renderForm =
    collection === 'blueprints'
      ? (value: string, onChange: (v: string) => void) => (
          <BlueprintForm value={value} onChange={onChange} tiers={tiers} checkSets={checkSets} />
        )
      : collection === 'flows'
        ? (value: string, onChange: (v: string) => void) => <FlowForm value={value} onChange={onChange} />
        : collection === 'loops'
          ? (value: string, onChange: (v: string) => void) => <LoopForm value={value} onChange={onChange} />
          : collection === 'specialists'
            ? (value: string, onChange: (v: string) => void) => (
                <SpecialistForm value={value} onChange={onChange} blueprintNames={blueprintNames} />
              )
            : collection === 'primers'
              ? (value: string, onChange: (v: string) => void) => (
                  <PrimerForm value={value} onChange={onChange} />
                )
              : undefined

  const runCommand = RUN_COMMANDS[collection]
  const runButton = runCommand ? (
    <ActionButton
      onClick={() => setRunning(true)}
      tone="live"
      size="sm"
    >
      <Play className="h-3 w-3" />
      Run
    </ActionButton>
  ) : undefined

  return (
    <>
      <EditorShell
        id={tabId({ type: 'source', resource: collection, name })}
        serverRaw={data?.raw}
        isLoading={isLoading}
        isError={isError}
        language={langFor(collection)}
        save={save}
        renderForm={renderForm}
        headerExtra={runButton}
      />
      {running && runCommand && (
        <RunDialog command={runCommand} name={name} onClose={() => setRunning(false)} />
      )}
    </>
  )
}

export function SourceEditor({ resource, name }: { resource: SourceResource; name: string }) {
  if (resource === 'manifest') return <ManifestEditor />
  if (resource === 'prompts') return <PromptEditor name={name} />
  return <CollectionEditor collection={resource} name={name} />
}
