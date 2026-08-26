// DiffView.tsx — A unified diff whose lines can be commented on.
//
// Line-addressable by design: a review note is only useful if it names a file
// and a line the agent can find again, so every post-image line carries its
// anchor (see lib/diff.ts). Deletions and hunk headers are not commentable —
// they do not exist in the result the reviewer is judging.
import { MessageSquarePlus } from 'lucide-react'
import { anchorKey, isCommentable, parseDiff } from '../lib/diff'
import type { DiffLine } from '../lib/diff'

const TONE: Record<string, string> = {
  add: 'text-live',
  del: 'text-error',
  hunk: 'text-accent',
  file: 'text-primary',
  meta: 'text-faint',
  context: 'text-muted',
}

export interface DraftComment {
  path: string
  line: number
  text: string
}

export function DiffView({
  diff,
  comments,
  onComment,
  activeAnchor,
}: {
  diff: string
  comments: Record<string, DraftComment>
  onComment: (path: string, line: number) => void
  activeAnchor?: string | null
}) {
  const lines = parseDiff(diff)

  if (lines.length === 0) {
    return <p className="p-3 text-[length:var(--ui-text-body)] text-faint">No change on this branch.</p>
  }

  return (
    // The diff scrolls inside its own box; the page never scrolls sideways.
    <div className="h-full overflow-auto">
      <table className="w-full border-collapse font-mono text-[length:var(--ui-text-body)]">
        <tbody>
          {lines.map((line: DiffLine, i) => {
            const commentable = isCommentable(line)
            const key = commentable ? anchorKey(line.path!, line.newLine!) : null
            const draft = key ? comments[key] : undefined
            return (
              <tr key={i} className={`${draft ? 'bg-accent/10' : ''} ${activeAnchor && activeAnchor === key ? 'bg-hover' : ''}`}>
                <td className="w-10 select-none px-2 text-right align-top text-faint">
                  {line.newLine ?? ''}
                </td>
                <td className={`whitespace-pre-wrap break-words px-2 align-top ${TONE[line.kind]}`}>
                  {line.text || ' '}
                  {draft && (
                    <div className="my-1 rounded-panel border border-accent/40 bg-panel px-2 py-1 font-sans text-[length:var(--ui-text-label)] text-muted">
                      {draft.text}
                    </div>
                  )}
                </td>
                <td className="w-9 align-top">
                  {commentable && (
                    <button
                      type="button"
                      aria-label={`Comment on ${key}`}
                      onClick={() => onComment(line.path!, line.newLine!)}
                      className="flex h-[var(--ui-control-h)] w-[var(--ui-control-h)] items-center justify-center text-faint hover:text-accent"
                    >
                      <MessageSquarePlus className="h-3.5 w-3.5" />
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
