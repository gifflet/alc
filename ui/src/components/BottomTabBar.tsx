// BottomTabBar.tsx — The mobile destinations.
//
// Five, chosen by what an operator decides from a phone: what's running, what
// needs me, what's next, what happened, everything else. Dashboard is absent on
// purpose — Fleet and Inbox answer its questions better, and its card grid is
// the worst offender on a narrow screen.
import { Inbox as InboxIcon, LayoutDashboard, LayoutGrid, ListTodo, MoreHorizontal } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { PrimaryView } from '../app/uiStore'

export interface Destination {
  view: PrimaryView | 'more'
  icon: LucideIcon
  label: string
}

export const DESTINATIONS: Destination[] = [
  // Dashboard leads because it is the project root: opening /projects/:id landed
  // on it while the bar highlighted "More", which told the operator they were
  // somewhere they were not. Runs moves to More — the Dashboard's Recent runs
  // card carries the shortcut.
  { view: 'dashboard', icon: LayoutDashboard, label: 'Home' },
  { view: 'inbox', icon: InboxIcon, label: 'Inbox' },
  { view: 'fleet', icon: LayoutGrid, label: 'Fleet' },
  { view: 'queue', icon: ListTodo, label: 'Queue' },
  { view: 'more', icon: MoreHorizontal, label: 'More' },
]

export function BottomTabBar({
  active,
  onSelect,
  inboxCount,
}: {
  active: string | null
  onSelect: (view: PrimaryView | 'more') => void
  inboxCount?: number
}) {
  return (
    <nav
      aria-label="Destinations"
      // pb-[env(...)] rather than an inline style: it is how the rest of the app
      // expresses spacing, and it survives in the DOM where a style object with
      // an env() value does not. The Android gesture bar overlaps the viewport
      // bottom; without this the last row of targets is unreachable.
      className="flex shrink-0 border-t border-border bg-panel pb-[env(safe-area-inset-bottom)]"
    >
      {DESTINATIONS.map(({ view, icon: Icon, label }) => {
        const selected = active === view
        return (
          <button
            key={view}
            type="button"
            aria-label={view === 'inbox' && inboxCount ? `${label}, ${inboxCount} waiting` : label}
            aria-current={selected ? 'page' : undefined}
            onClick={() => onSelect(view)}
            className={`relative flex min-h-[var(--ui-rail-btn)] flex-1 flex-col items-center justify-center gap-0.5 py-1.5 transition-colors duration-120 ${
              selected ? 'text-accent' : 'text-faint'
            }`}
          >
            <Icon className="h-5 w-5" strokeWidth={1.75} />
            <span className="text-[length:var(--ui-text-label)]">{label}</span>
            {view === 'inbox' && Boolean(inboxCount) && (
              <span className="absolute right-1/4 top-1 min-w-[14px] rounded-full bg-accent px-1 text-center text-[length:var(--ui-text-label)] font-medium leading-[14px] text-base">
                {inboxCount}
              </span>
            )}
          </button>
        )
      })}
    </nav>
  )
}
