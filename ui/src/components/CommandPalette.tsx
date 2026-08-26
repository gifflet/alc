// CommandPalette.tsx — Cmd+K: reach anything in two keystrokes.
//
// Built from what the query cache already holds, so opening it costs no request.
// Ranking and grouping live in lib/commandIndex.ts; this file owns the keyboard
// model and the rendering.
import { useEffect, useMemo, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { groupCommands, rankCommands } from '../lib/commandIndex'
import type { Command, CommandKind } from '../lib/commandIndex'

const KIND_LABEL: Record<CommandKind, string> = {
  view: 'Views',
  action: 'Actions',
  blueprint: 'Blueprints',
  flow: 'Flows',
  specialist: 'Specialists',
  loop: 'Loops',
  primer: 'Primers',
  prompt: 'Prompts',
  run: 'Runs',
  task: 'Queue',
  branch: 'Branches',
}

export function CommandPalette({
  commands,
  onClose,
}: {
  commands: Command[]
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const restoreRef = useRef<HTMLElement | null>(null)

  const ranked = useMemo(() => rankCommands(commands, query).slice(0, 40), [commands, query])
  const groups = useMemo(() => groupCommands(ranked), [ranked])

  useEffect(() => {
    restoreRef.current = document.activeElement as HTMLElement | null
    inputRef.current?.focus()
    // Escape must return the operator exactly where they were, or the palette
    // becomes a trap that costs more than the navigation it saved.
    return () => restoreRef.current?.focus?.()
  }, [])

  useEffect(() => setCursor(0), [query])

  const activate = (command: Command | undefined) => {
    if (!command) return
    command.run()
    onClose()
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCursor((c) => Math.min(c + 1, ranked.length - 1))
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCursor((c) => Math.max(c - 1, 0))
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      activate(ranked[cursor])
    }
  }

  let flatIndex = -1

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        className="mt-[10vh] flex max-h-[70vh] w-full max-w-[560px] flex-col rounded-[var(--radius-lg)] bg-panel shadow-[var(--elev-3)] ring-1 ring-border/50"
      >
        <div className="flex min-h-[var(--ui-control-h)] shrink-0 items-center gap-2 border-b border-border px-[var(--ui-pad-x)]">
          <Search className="h-4 w-4 shrink-0 text-faint" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search commands"
            placeholder="Go to a view, unit, run or branch…"
            className="min-h-[var(--ui-control-h)] w-full bg-transparent text-[length:var(--ui-text-body)] text-primary outline-none placeholder:text-faint"
          />
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {ranked.length === 0 ? (
            <p className="p-3 text-[length:var(--ui-text-body)] text-faint">Nothing matches.</p>
          ) : (
            groups.map((group) => (
              <div key={group.kind}>
                <p className="px-[var(--ui-pad-x)] pt-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
                  {KIND_LABEL[group.kind]}
                </p>
                <ul>
                  {group.items.map((command) => {
                    flatIndex += 1
                    const selected = flatIndex === cursor
                    return (
                      <li key={command.id}>
                        <button
                          type="button"
                          aria-current={selected ? 'true' : undefined}
                          onClick={() => activate(command)}
                          className={`flex min-h-[var(--ui-control-h)] w-full items-center gap-2 px-[var(--ui-pad-x)] py-1 text-left ${
                            selected ? 'bg-hover' : ''
                          }`}
                        >
                          <span className="min-w-0 flex-1 truncate text-[length:var(--ui-text-body)] text-primary">
                            {command.label}
                          </span>
                          {command.hint && (
                            <span className="shrink-0 truncate text-[length:var(--ui-text-label)] text-faint">
                              {command.hint}
                            </span>
                          )}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
