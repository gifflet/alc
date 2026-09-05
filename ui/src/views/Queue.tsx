// Queue.tsx — Pending tasks + archived (done) tasks with enqueue/retry/delete,
// plus the unmerged alc/* branches those drains produce (land/discard).
import { Fragment, useState } from 'react'
import { Check,
  ChevronDown,
  ChevronRight,
  GitMerge,
  ListTodo,
  Play,
  Plus,
  RotateCcw,
  Trash2,
} from 'lucide-react'
import { useArchiveSignal,
  useBranches,
  useDeletePending,
  useDiscardBranches,
  useEnqueueBatch,
  useEnqueueTask,
  useIngestSignal,
  useLandBranches,
  useQueue,
  useRetryQueue,
  useSignals,
} from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { ConfirmDialog, Dialog, DialogButton } from '../components/Dialog'
import { DataTable } from '../components/DataTable'
import type { Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { Checkbox, Field, NumberInput, Select } from '../components/fields'
import { Loading, Pill } from '../components/primitives'
import { RelativeTime } from '../components/RelativeTime'
import type { Tone } from '../components/StatusDot'
import { EnqueueDialog } from './EnqueueDialog'
import { SignalIngestDialog } from './SignalIngestDialog'
import { ActionButton } from '../components/ActionButton'
import { ApiError } from '../api/client'
import type {
  Branch,
  DoneTask,
  FlowReport,
  LandResult,
  PendingTask,
  QueueTask,
  Signal,
  SignalIngestPayload,
} from '../api/types'

function firstLine(text: string): string {
  return text.split('\n')[0]
}

/** A re-executed task's attempt number — surfaced so a retry is visible at a glance. */
function RetryBadge({ task }: { task: QueueTask | null }) {
  if (!task?.retries) return null
  return <Pill tone="warn">retry #{task.retries}</Pill>
}

/** The full task body — for a retry this shows the lineage root it descends from
 * plus the carried failure feedback appended below the intent, both of which the
 * one-line summary hides. */
function TaskBody({ task }: { task: QueueTask }) {
  return (
    <div className="border-l-2 border-border bg-base px-3 py-2">
      {task.retry_of && (
        <div className="mb-1 font-mono text-[length:var(--ui-text-label)] text-faint">
          ↩ retry lineage of <span className="text-muted">{task.retry_of}</span>
        </div>
      )}
      <pre className="whitespace-pre-wrap font-mono text-[length:var(--ui-text-label)] leading-relaxed text-muted">
        {task.task}
      </pre>
    </div>
  )
}

function DrainDialog({ pending, onClose }: { pending: number; onClose: () => void }) {
  const start = useStartExec()
  const [concurrency, setConcurrency] = useState<number | ''>(1)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setSaving(true)
    setError(null)
    try {
      await start('tick', concurrency === '' ? {} : { concurrency })
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to start.')
      setSaving(false)
    }
  }

  return (
    <Dialog
      title="Drain queue"
      onClose={onClose}
      footer={
        <>
          <DialogButton tone="ghost" onClick={onClose}>
            Cancel
          </DialogButton>
          <DialogButton onClick={submit} disabled={saving}>
            Drain
          </DialogButton>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-[length:var(--ui-text-body)] text-muted">
          Runs {pending === 1 ? 'the 1 pending task' : `all ${pending} pending tasks`} once (alc tick), then
          exits. One engine turn each.
        </p>
        <Field label="Concurrency">
          <NumberInput value={concurrency} onChange={setConcurrency} placeholder="1" />
        </Field>
        {error && <p className="text-[length:var(--ui-text-label)] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}

function apiMessage(error: unknown): string | null {
  if (error instanceof ApiError) return error.message
  return error ? 'Request failed.' : null
}

/** The delivery mode for Land's push/PR last mile (DeliverySpec):
 * a single select for the whole section rather than one per row — a land
 * always pushes the CURRENT branch (never a per-row target), so the choice is
 * one decision for the panel, not one per unmerged branch. */
const LAND_MODE_OPTIONS = [
  { value: 'local', label: 'Local only' },
  { value: 'push', label: 'Push' },
  { value: 'pr', label: 'Open PR' },
]

/** The unmerged `alc/*` branches a drain leaves behind (each demand's own
 * worktree exit-commit), with Land/Discard actions. Lives on Queue rather
 * than a dedicated view: these branches are exactly what draining the queue
 * produces, and Queue already owns the house destructive-action pattern
 * (see the pending-task delete confirm below) that Discard reuses. */
function BranchesSection() {
  const id = useProjectId()
  const { data, isLoading } = useBranches(id)
  const land = useLandBranches(id)
  const discard = useDiscardBranches(id)
  const [landMode, setLandMode] = useState<'local' | 'push' | 'pr'>('local')
  const [landReport, setLandReport] = useState<LandResult | null>(null)
  const [discarding, setDiscarding] = useState<string | null>(null)
  const [pruneWorktrees, setPruneWorktrees] = useState(false)
  const [gcBundles, setGcBundles] = useState(false)
  const [olderThanDays, setOlderThanDays] = useState<number | ''>(30)

  if (isLoading) return null

  if (!data?.available) {
    return (
      <section className="min-w-0">
        <h3 className="mb-1 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Branches</h3>
        <p className="text-[length:var(--ui-text-body)] text-faint">Not inside a git repository — branch actions are unavailable.</p>
      </section>
    )
  }

  const unmerged = data.branches.filter((b) => !b.merged)

  const doLand = (name: string) => {
    setLandReport(null)
    land.mutate(
      { branches: [name], mode: landMode === 'local' ? undefined : landMode },
      { onSuccess: (report) => setLandReport(report) },
    )
  }

  const confirmDiscard = () => {
    if (!discarding) return
    discard.mutate(
      {
        branches: [discarding],
        ...(pruneWorktrees ? { worktrees: true } : {}),
        ...(gcBundles && olderThanDays !== '' ? { bundles: { older_than_days: olderThanDays } } : {}),
      },
      {
        onSuccess: () => {
          setDiscarding(null)
          setPruneWorktrees(false)
          setGcBundles(false)
        },
      },
    )
  }

  const columns: Column<Branch>[] = [
    { key: 'name', header: 'Branch', className: 'font-mono text-muted', priority: 1, render: (b) => b.name },
    { key: 'label', header: 'Label', className: 'w-24 font-mono text-faint', priority: 2, render: (b) => b.label },
    {
      key: 'actions',
      priority: 1,
      header: '',
      className: 'w-36',
      render: (b) => (
        <div className="flex items-center gap-2">
          <ActionButton
            aria-label={`Land ${b.name}`}
            onClick={() => doLand(b.name)}
            disabled={land.isPending}
            tone="live"
            size="sm"
          >
            <GitMerge className="h-3 w-3" />
            Land
          </ActionButton>
          <ActionButton
            aria-label={`Discard ${b.name}`}
            onClick={() => setDiscarding(b.name)}
            tone="ghost"
            size="sm"
          >
            <Trash2 className="h-3 w-3" />
            Discard
          </ActionButton>
        </div>
      ),
    },
  ]

  return (
    <section className="min-w-0">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
          Branches <span className="tabular">({unmerged.length})</span>
        </h3>
        <div className="flex items-center gap-1.5">
          <span className="text-[length:var(--ui-text-label)] text-faint">Land mode</span>
          <div className="w-32">
            <Select
              value={landMode}
              onChange={(v) => setLandMode(v as 'local' | 'push' | 'pr')}
              options={LAND_MODE_OPTIONS}
            />
          </div>
        </div>
      </div>
      {unmerged.length === 0 ? (
        <p className="text-[length:var(--ui-text-body)] text-faint">No unmerged alc/* branches.</p>
      ) : (
        <DataTable columns={columns} rows={unmerged} rowKey={(b) => b.name} />
      )}
      {landReport && landReport.conflicted.length > 0 && (
        <p className="mt-1 text-[length:var(--ui-text-label)] text-warn">
          Left for manual resolution: {landReport.conflicted.join(', ')}
        </p>
      )}
      {landReport?.warning && (
        <p className="mt-1 text-[length:var(--ui-text-label)] text-warn">Delivery warning: {landReport.warning}</p>
      )}
      {apiMessage(land.error) && <p className="mt-1 text-[length:var(--ui-text-label)] text-error">{apiMessage(land.error)}</p>}
      {apiMessage(discard.error) && (
        <p className="mt-1 text-[length:var(--ui-text-label)] text-error">{apiMessage(discard.error)}</p>
      )}
      {discarding && (
        <ConfirmDialog
          title="Discard branch?"
          message={
            <div className="flex flex-col gap-2">
              <p>{`This permanently deletes ${discarding}. This cannot be undone.`}</p>
              <Checkbox
                checked={pruneWorktrees}
                onChange={setPruneWorktrees}
                label="Also prune orphaned git worktrees"
              />
              <Checkbox
                checked={gcBundles}
                onChange={setGcBundles}
                label="Also delete bundle files older than…"
              />
              {gcBundles && (
                <div className="flex items-center gap-2 pl-5">
                  <div className="w-20">
                    <NumberInput value={olderThanDays} onChange={setOlderThanDays} placeholder="30" />
                  </div>
                  <span className="text-[length:var(--ui-text-label)] text-faint">days</span>
                </div>
              )}
            </div>
          }
          confirmLabel="Discard"
          onConfirm={confirmDiscard}
          onCancel={() => setDiscarding(null)}
        />
      )}
    </section>
  )
}

const SIGNAL_KIND_TONE: Record<Signal['kind'], Tone> = {
  error: 'error',
  feedback: 'accent',
  issue: 'warn',
  review: 'idle',
}

/** Pending signals (`alc signal ingest`/`signal list`) — typed external events
 * (an error tracker alert, operator feedback, an issue, a review comment) a
 * loop's `signals` replenish later drains into demands. Lives on Queue next to
 * Branches: both are queue-adjacent panels for material that feeds (or is
 * produced alongside) queue tasks, not full views of their own — the list is
 * four columns wide, the same scale as Branches. */
function SignalsSection() {
  const id = useProjectId()
  const { data, isLoading } = useSignals(id)
  const ingest = useIngestSignal(id)
  const archive = useArchiveSignal(id)
  const [ingesting, setIngesting] = useState(false)

  if (isLoading) return null
  const signals = data ?? []

  const closeIngest = () => {
    setIngesting(false)
    ingest.reset()
  }

  const submitIngest = (payload: SignalIngestPayload) =>
    ingest.mutate(payload, { onSuccess: closeIngest })

  const columns: Column<Signal>[] = [
    {
      key: 'kind',
      priority: 2,
      header: 'Kind',
      className: 'w-20',
      render: (s) => <Pill tone={SIGNAL_KIND_TONE[s.kind]}>{s.kind}</Pill>,
    },
    { key: 'source', header: 'Source', className: 'w-28 font-mono text-faint', priority: 3, render: (s) => s.source },
    { key: 'title', header: 'Title', className: 'text-muted', priority: 1, render: (s) => s.title },
    {
      key: 'age',
      priority: 2,
      header: 'Age',
      className: 'w-20',
      render: (s) => <RelativeTime value={s.ts} />,
    },
    {
      key: 'archive',
      priority: 2,
      header: '',
      className: 'w-10',
      // A handled signal had no exit (finding 40): the library's archive move
      // existed with no operator verb over it, so an addressed signal stayed
      // "pending" and the next listen pass would re-plan finished work.
      render: (s) => (
        <button
          type="button"
          aria-label={`Archive signal ${s.title}`}
          title="Mark handled (moves into signals/done/)"
          disabled={archive.isPending}
          onClick={() => archive.mutate(s.path.split('/').pop()!)}
          className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint alc-reveal hover:text-primary"
        >
          <Check className="h-3.5 w-3.5" />
        </button>
      ),
    },
  ]

  return (
    <section className="min-w-0">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
          Signals <span className="tabular">({signals.length})</span>
        </h3>
        <ActionButton
          onClick={() => setIngesting(true)}
          tone="accent"
          size="sm"
        >
          <Plus className="h-3 w-3" />
          Ingest signal
        </ActionButton>
      </div>
      {signals.length === 0 ? (
        <p className="text-[length:var(--ui-text-body)] text-faint">No pending signals.</p>
      ) : (
        <DataTable columns={columns} rows={signals} rowKey={(s) => s.path} />
      )}
      {apiMessage(ingest.error) && (
        <p className="mt-1 text-[length:var(--ui-text-label)] text-error">{apiMessage(ingest.error)}</p>
      )}
      {ingesting && (
        <SignalIngestDialog
          onClose={closeIngest}
          onSubmit={submitIngest}
          saving={ingest.isPending}
          error={ingest.error instanceof ApiError ? ingest.error.message : null}
        />
      )}
    </section>
  )
}

function ReportSummary({ report }: { report: FlowReport }) {
  return (
    <div className="border-l-2 border-border bg-base px-3 py-2 text-[length:var(--ui-text-label)]">
      <div className="flex flex-wrap gap-4 font-mono text-faint">
        <span>flow: {report.flow}</span>
        <span>engine: {report.engine}</span>
        <span>stages: {report.stages.length}</span>
        <span>
          scorecard: span={report.scorecard.span} passes={report.scorecard.passes} streak=
          {report.scorecard.streak} touch={report.scorecard.touch}
        </span>
        {report.commit_sha && <span>commit: {report.commit_sha.slice(0, 10)}</span>}
      </div>
    </div>
  )
}

function DoneRows({ done, onRetry }: { done: DoneTask[]; onRetry: (stem: string) => void }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[length:var(--ui-text-body)]">
        <thead>
          <tr className="border-b border-border text-left text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
            <th className="w-6 px-2 py-1" />
            <th className="px-2 py-1 font-medium">Task</th>
            <th className="hidden w-20 px-2 py-1 font-medium sm:table-cell">Result</th>
            <th className="w-24 px-2 py-1 font-medium">When</th>
            <th className="w-16 px-2 py-1 font-medium" />
          </tr>
        </thead>
        <tbody>
          {done.map((d) => {
            const open = expanded === d.stem
            const success = d.report?.success ?? null
            // A non-isolated success leaves its edits UNCOMMITTED in the live
            // working tree — no branch, no Inbox item, nothing anywhere said
            // "the drain changed these files" (finding 43). Say it on the row.
            const treeFiles: string[] = (d.report?.stages ?? [])
              .flatMap((st: { changed_files?: string[] }) => st.changed_files ?? [])
            // isolate !== true is load-bearing: an ISOLATED demand's edits go
            // to a worktree branch even when its flow declares no commit
            // (FlowReport.commit_sha stays null), and the badge falsely
            // claimed nine branch-bound cycle-3 demands had edited the live
            // tree — caught on the device, round 11's closing sweep.
            const editedTree =
              success === true &&
              d.task?.isolate !== true &&
              !d.report?.commit_sha &&
              treeFiles.length > 0
            return (
              <Fragment key={d.stem}>
                <tr
                  role="button"
                  tabIndex={0}
                  aria-expanded={open}
                  onClick={() => setExpanded(open ? null : d.stem)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setExpanded(open ? null : d.stem)
                    }
                  }}
                  className="h-[var(--ui-row-h)] cursor-pointer border-b border-border/15 transition-colors duration-120 hover:bg-hover"
                >
                  <td className="px-2">
                    {d.report || d.task ? (
                      open ? (
                        <ChevronDown className="h-3.5 w-3.5 text-faint" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 text-faint" />
                      )
                    ) : null}
                  </td>
                  <td className="w-full max-w-0 px-2 text-muted">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="min-w-0 truncate">{d.task ? firstLine(d.task.task) : d.stem}</span>
                      <RetryBadge task={d.task} />
                    </span>
                    {/* On a phone the table scrolls sideways and the Result
                        column sits off-viewport — the outcome pills were
                        technically present and practically invisible (round 10
                        device validation). Below sm they ride with the task. */}
                    {success !== null && (
                      <span className="mt-0.5 flex items-center gap-1.5 sm:hidden">
                        <Pill tone={success ? 'live' : 'error'}>{success ? 'ok' : 'failed'}</Pill>
                        {editedTree && (
                          <Pill tone="warn" title={`This non-isolated run edited the working tree directly: ${treeFiles.join(', ')}`}>
                            edited tree
                          </Pill>
                        )}
                      </span>
                    )}
                  </td>
                  <td className="hidden px-2 sm:table-cell">
                    {success === null ? (
                      <span className="text-faint">—</span>
                    ) : (
                      <span className="flex items-center gap-1.5">
                        <Pill tone={success ? 'live' : 'error'}>{success ? 'ok' : 'failed'}</Pill>
                        {editedTree && (
                          <Pill tone="warn" title={`This non-isolated run edited the working tree directly: ${treeFiles.join(', ')}`}>
                            edited tree
                          </Pill>
                        )}
                      </span>
                    )}
                  </td>
                  <td className="px-2">
                    <RelativeTime value={d.mtime} />
                  </td>
                  <td className="px-2">
                    {d.outstanding && (
                      <ActionButton
                        aria-label={`Retry ${d.stem}`}
                        onClick={(e) => {
                          e.stopPropagation()
                          onRetry(d.stem)
                        }}
                        tone="ghost"
                        size="sm"
                      >
                        <RotateCcw className="h-3 w-3" />
                        retry
                      </ActionButton>
                    )}
                  </td>
                </tr>
                {open && (
                  <tr>
                    <td colSpan={5} className="p-0">
                      {d.task && <TaskBody task={d.task} />}
                      {d.report && <ReportSummary report={d.report} />}
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function PendingRows({
  pending,
  onDelete,
}: {
  pending: PendingTask[]
  onDelete: (stem: string) => void
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[length:var(--ui-text-body)]">
        <thead>
          <tr className="border-b border-border text-left text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
            <th className="w-6 px-2 py-1" />
            <th className="px-2 py-1 font-medium">Task</th>
            <th className="w-20 px-2 py-1 font-medium">Kind</th>
            <th className="w-28 px-2 py-1 font-medium">Unit</th>
            <th className="w-16 px-2 py-1 font-medium">Isolate</th>
            <th className="w-28 px-2 py-1 font-medium">Depends on</th>
            <th className="w-10 px-2 py-1 font-medium" />
          </tr>
        </thead>
        <tbody>
          {pending.map((p) => {
            const open = expanded === p.stem
            return (
              <Fragment key={p.stem}>
                <tr
                  role="button"
                  tabIndex={0}
                  aria-expanded={open}
                  onClick={() => setExpanded(open ? null : p.stem)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setExpanded(open ? null : p.stem)
                    }
                  }}
                  className="group h-[var(--ui-row-h)] cursor-pointer border-b border-border/15 transition-colors duration-120 hover:bg-hover"
                >
                  <td className="px-2">
                    {open ? (
                      <ChevronDown className="h-3.5 w-3.5 text-faint" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 text-faint" />
                    )}
                  </td>
                  <td className="truncate px-2 text-muted">
                    <span className="flex items-center gap-2">
                      <span className="truncate">{firstLine(p.task.task)}</span>
                      <RetryBadge task={p.task} />
                    </span>
                  </td>
                  <td className="px-2 font-mono text-faint">{p.task.kind}</td>
                  <td className="px-2 text-muted">{p.task.name ?? p.task.flow}</td>
                  <td className="px-2">
                    {p.task.isolate ? (
                      <Pill tone="accent">yes</Pill>
                    ) : (
                      <span className="text-faint">no</span>
                    )}
                  </td>
                  <td className="px-2 font-mono text-faint">
                    {p.task.depends_on.length ? p.task.depends_on.join(', ') : '—'}
                  </td>
                  <td className="px-2">
                    <button
                      type="button"
                      aria-label={`Delete ${p.stem}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        onDelete(p.stem)
                      }}
                      className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint alc-reveal hover:text-error"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
                {open && (
                  <tr>
                    <td colSpan={7} className="p-0">
                      <TaskBody task={p.task} />
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function Queue() {
  const id = useProjectId()
  const { data, isLoading } = useQueue(id)
  const enqueue = useEnqueueTask(id)
  const enqueueBatch = useEnqueueBatch(id)
  const retry = useRetryQueue(id)
  const del = useDeletePending(id)
  const [enqueuing, setEnqueuing] = useState(false)
  const [draining, setDraining] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  if (isLoading) return <Loading />
  const pending = data?.pending ?? []
  const done = data?.done ?? []
  const failures = done.filter((d) => d.outstanding)

  const submitEnqueue = (task: Parameters<typeof enqueue.mutate>[0]) =>
    enqueue.mutate(task, {
      onSuccess: () => {
        setEnqueuing(false)
        enqueue.reset()
      },
    })

  const submitEnqueueBatch = (tasks: Parameters<typeof enqueueBatch.mutate>[0]) =>
    enqueueBatch.mutate(tasks, {
      onSuccess: () => {
        setEnqueuing(false)
        enqueueBatch.reset()
      },
    })

  const confirmDelete = () => {
    if (!deleting) return
    del.mutate(deleting, { onSuccess: () => setDeleting(null) })
  }

  const empty = pending.length === 0 && done.length === 0

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-panel px-4 py-2">
        <h2 className="text-[length:var(--ui-text-body)] font-medium text-primary">Queue</h2>
        <div className="flex items-center gap-2">
          {failures.length > 0 && (
            <ActionButton
              onClick={() => retry.mutate({ all: true })}
              tone="ghost"
              size="sm"
            >
              <RotateCcw className="h-3 w-3" />
              Retry all failures
            </ActionButton>
          )}
          {pending.length > 0 && (
            <ActionButton
              onClick={() => setDraining(true)}
              tone="live"
              size="sm"
            >
              <Play className="h-3 w-3" />
              Drain queue
            </ActionButton>
          )}
          <ActionButton
            onClick={() => setEnqueuing(true)}
            tone="accent"
            size="sm"
          >
            <Plus className="h-3 w-3" />
            Enqueue task
          </ActionButton>
        </div>
      </div>

      {empty ? (
        <EmptyState icon={ListTodo} message="The queue is empty — enqueue a task to fill it." />
      ) : (
        <div className="flex min-w-0 flex-col gap-4 p-4">
          <section className="min-w-0">
            <h3 className="mb-1 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
              Pending <span className="tabular">({pending.length})</span>
            </h3>
            {pending.length === 0 ? (
              <p className="text-[length:var(--ui-text-body)] text-faint">Nothing pending.</p>
            ) : (
              <PendingRows pending={pending} onDelete={setDeleting} />
            )}
          </section>

          <section className="min-w-0">
            <h3 className="mb-1 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
              Done <span className="tabular">({done.length})</span>
            </h3>
            {done.length === 0 ? (
              <p className="text-[length:var(--ui-text-body)] text-faint">No archived tasks.</p>
            ) : (
              <DoneRows done={done} onRetry={(stem) => retry.mutate({ stem })} />
            )}
          </section>
        </div>
      )}

      <div className="flex flex-col gap-4 border-t border-border p-4">
        <BranchesSection />
        <SignalsSection />
      </div>

      {enqueuing && (
        <EnqueueDialog
          onClose={() => {
            setEnqueuing(false)
            enqueue.reset()
            enqueueBatch.reset()
          }}
          onSubmit={submitEnqueue}
          onSubmitBatch={submitEnqueueBatch}
          pending={pending}
          saving={enqueue.isPending || enqueueBatch.isPending}
          error={
            enqueue.error instanceof ApiError
              ? enqueue.error.message
              : enqueueBatch.error instanceof ApiError
                ? enqueueBatch.error.message
                : null
          }
        />
      )}

      {draining && <DrainDialog pending={pending.length} onClose={() => setDraining(false)} />}

      {deleting && (
        <ConfirmDialog
          title="Delete pending task?"
          message="This removes the queued task before it runs."
          confirmLabel="Delete"
          onConfirm={confirmDelete}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  )
}
