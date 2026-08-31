// Inbox.tsx — What needs a human right now.
//
// ALC runs unattended; the operator is ON the loop, not in it. This is the one
// screen that answers "what needs me?" — outstanding failures, work waiting to
// land, and loops a backstop halted — each with its action inline.
//
// There is no read/unread store: an item leaves because it was ACTED on. A
// dismiss-without-acting button would let the control room hide a truth about
// the project, which is the one thing it must never do.
import { useState } from 'react'
import { Eye, GitMerge, Inbox as InboxIcon, RefreshCw, RotateCcw, Trash2 } from 'lucide-react'
import { useDiscardBranches, useInbox, useLandBranches, useRetryQueue } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { uiStore } from '../app/uiStore'
import { ConfirmDialog } from '../components/Dialog'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/primitives'
import { StatusDot } from '../components/StatusDot'
import type { InboxItem, InboxKind } from '../api/types'

const KIND_LABEL: Record<InboxKind, string> = {
  failure: 'failure',
  branch: 'to land',
  loop: 'loop stopped',
}

function Action({
  icon: Icon,
  label,
  onClick,
  disabled,
  tone,
}: {
  icon: typeof GitMerge
  label: string
  onClick: () => void
  disabled?: boolean
  tone?: 'error'
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex h-[var(--ui-control-h)] min-h-[var(--ui-control-h)] items-center gap-1.5 rounded-panel border border-border px-2 text-[length:var(--ui-text-label)] transition-colors duration-120 hover:bg-hover disabled:opacity-40 ${
        tone === 'error' ? 'text-error' : 'text-muted'
      }`}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  )
}

export function Inbox() {
  const id = useProjectId()
  const { data, isLoading } = useInbox(id)
  const retry = useRetryQueue(id)
  const land = useLandBranches(id)
  const discard = useDiscardBranches(id)
  const [discarding, setDiscarding] = useState<string | null>(null)
  // Discard asked before throwing the machine's work away; Land did not ask
  // before writing it into the repository's history. The protection was on the
  // wrong side — losing an agent's branch is cheap, and unwinding a merge is
  // not.
  const [landing, setLanding] = useState<string | null>(null)

  if (isLoading) return <Loading />
  const items = data?.items ?? []

  if (items.length === 0) {
    return <EmptyState icon={InboxIcon} message="Nothing needs you. No failures, no branches to land, no halted loops." />
  }

  const actionsFor = (item: InboxItem) => {
    if (item.kind === 'failure') {
      // A queued retry has NOT resolved the failure, so the item stays. But the
      // operator must see that one is already waiting, or they queue it twice.
      return (
        <Action
          icon={RotateCcw}
          label={item.retry_pending ? 'Retry queued' : 'Retry'}
          disabled={retry.isPending || item.retry_pending}
          onClick={() => retry.mutate({ stem: item.stem })}
        />
      )
    }
    if (item.kind === 'branch') {
      return (
        <>
          <Action
            icon={Eye}
            label="Review"
            onClick={() =>
              uiStore.openTab({
                target: { type: 'review', branch: item.branch! },
                title: item.branch!,
              })
            }
          />
          <Action
            icon={GitMerge}
            label="Land"
            disabled={land.isPending}
            onClick={() => setLanding(item.branch!)}
          />
          <Action
            icon={Trash2}
            label="Discard"
            tone="error"
            disabled={discard.isPending}
            onClick={() => setDiscarding(item.branch!)}
          />
        </>
      )
    }
    return (
      <Action
        icon={RefreshCw}
        label="Open loop"
        onClick={() => uiStore.openTab({ target: { type: 'loop', name: item.loop! }, title: item.loop! })}
      />
    )
  }

  return (
    <div className="h-full overflow-auto">
      <ul className="flex flex-col">
        {items.map((item) => (
          <li
            key={item.id}
            className="flex flex-col gap-[var(--ui-gap)] border-b border-border/15 px-[var(--ui-pad-x)] py-[var(--ui-pad-y)]"
          >
            <div className="flex min-w-0 items-center gap-2">
              <StatusDot
                tone={
                  item.kind === 'failure' || item.verified === false ? 'error' : 'accent'
                }
              />
              <span className="min-w-0 flex-1 truncate text-[length:var(--ui-text-title)] text-primary">
                {item.title}
              </span>
              {/* "TO LAND" is an instruction, and it was printed beside a row
                  saying the checks did not pass. The badge has to agree with the
                  sentence under it. */}
              <span
                className={`shrink-0 text-[length:var(--ui-text-label)] uppercase tracking-wide ${
                  item.verified === false ? 'text-error' : 'text-faint'
                }`}
              >
                {item.verified === false ? 'unverified' : KIND_LABEL[item.kind]}
              </span>
            </div>
            <p className="text-[length:var(--ui-text-body)] text-muted">
              {item.reason}
              {item.retry_pending && (
                <span className="text-faint"> · a retry is queued, not yet run</span>
              )}
            </p>
            <div className="flex flex-wrap gap-2">{actionsFor(item)}</div>
          </li>
        ))}
      </ul>

      {landing && (
        <ConfirmDialog
          title="Land branch"
          // An unverified branch can still be landed — this codebase warns and
          // never refuses, and the operator may have read the diff and decided.
          // But the fact cannot be discoverable only three views away.
          message={
            items.find((i) => i.branch === landing)?.verified === false
              ? `${landing} committed work whose checks did NOT pass — the run failed or was interrupted. Landing merges it into your history anyway. Read the diff first.`
              : `Land ${landing} into your current branch? This merges the agent's commits into your history — review the diff first if you have not.`
          }
          confirmLabel="Land"
          tone={items.find((i) => i.branch === landing)?.verified === false ? 'error' : 'accent'}
          onConfirm={() => {
            land.mutate({ branches: [landing] })
            setLanding(null)
          }}
          onCancel={() => setLanding(null)}
        />
      )}

      {discarding && (
        <ConfirmDialog
          title="Discard branch"
          message={`Discard ${discarding}? This force-deletes the branch and its work.`}
          confirmLabel="Discard"
          tone="error"
          onConfirm={() => {
            discard.mutate({ branches: [discarding] })
            setDiscarding(null)
          }}
          onCancel={() => setDiscarding(null)}
        />
      )}
    </div>
  )
}
