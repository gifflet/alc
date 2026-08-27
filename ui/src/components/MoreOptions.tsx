// MoreOptions.tsx — Fold the controls a newcomer should not have to answer.
//
// Engine, tier and isolation each have a correct default sitting in the
// manifest. Presenting all three at the same weight as the task turns "describe
// what you want" into a four-question form, and three of those questions need
// vocabulary the person does not have yet.
//
// Collapsed, not removed: someone who wants to pick an engine finds it in one
// click, and nothing they could reach before became unreachable.
import { useState } from 'react'
import type { ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'

export function MoreOptions({
  children,
  label = 'Options',
  hint,
}: {
  children: ReactNode
  label?: string
  hint?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex min-h-[var(--ui-control-h)] w-fit items-center gap-1 rounded-xs pr-2 text-[length:var(--ui-text-label)] text-faint transition-colors duration-120 hover:text-primary"
      >
        <ChevronRight
          className={`h-3.5 w-3.5 transition-transform duration-120 ${open ? 'rotate-90' : ''}`}
        />
        {label}
        {!open && hint && <span className="ml-1.5 text-faint">— {hint}</span>}
      </button>
      {open && <div className="flex flex-col gap-3">{children}</div>}
    </div>
  )
}
