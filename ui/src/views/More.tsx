// More.tsx — Everything that is not a bottom-tab destination.
//
// The phone keeps five resident destinations; the rest stay reachable here
// rather than being cut. Config is included because reading a Blueprint is a
// legitimate phone task — editing it is not (SourceEditor is read-only there).
import { ChevronRight, SunMoon, Zap } from 'lucide-react'
import {
  FileCog,
  GitCompare,
  Radio,
  LineChart,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  Wand2,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { uiStore } from '../app/uiStore'
import { setTheme, useTheme } from '../app/useTheme'
import type { PrimaryView } from '../app/uiStore'

interface Entry {
  view: PrimaryView
  icon: LucideIcon
  label: string
  hint: string
}

const ENTRIES: Entry[] = [
  { view: 'runs', icon: Radio, label: 'Runs', hint: 'Every run log, newest first' },
  { view: 'loops', icon: RefreshCw, label: 'Loops', hint: 'Autonomous loops and their ledgers' },
  { view: 'conduct', icon: Wand2, label: 'Conduct', hint: 'Turn a goal into Flows' },
  { view: 'team', icon: Users, label: 'Team', hint: 'Archetype packs and mix health' },
  { view: 'metrics', icon: LineChart, label: 'Metrics', hint: 'Metric-check time series' },
  { view: 'compare', icon: GitCompare, label: 'Compare', hint: 'Explored variants, side by side' },
  { view: 'checks', icon: ShieldCheck, label: 'Checks', hint: 'Check history and flake score' },
  { view: 'run-configs', icon: SlidersHorizontal, label: 'Run Configurations', hint: 'Saved dispatch presets' },
]

const VIEW_TITLE: Record<string, string> = {
  runs: 'Runs',
  loops: 'Loops',
  conduct: 'Conduct',
  team: 'Team',
  metrics: 'Metrics',
  compare: 'Compare',
  checks: 'Checks',
  'run-configs': 'Run Configurations',
}

export function More({ onOpenSpike }: { onOpenSpike?: () => void }) {
  const theme = useTheme()
  return (
    <div className="h-full overflow-auto">
      <ul className="flex flex-col">
        {ENTRIES.map(({ view, icon: Icon, label, hint }) => (
          <li key={view}>
            <button
              type="button"
              onClick={() =>
                uiStore.openTab({ target: { type: 'view', view }, title: VIEW_TITLE[view], closable: false })
              }
              className="flex min-h-[var(--ui-rail-btn)] w-full items-center gap-3 border-b border-border/15 px-[var(--ui-pad-x)] py-2 text-left hover:bg-hover"
            >
              <Icon className="h-5 w-5 shrink-0 text-faint" strokeWidth={1.75} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-[length:var(--ui-text-body)] text-primary">{label}</span>
                <span className="truncate text-[length:var(--ui-text-label)] text-faint">{hint}</span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-faint" />
            </button>
          </li>
        ))}
        {/* Spike is an action, not a destination, so it has no bottom tab and
            no view to open. Without this row the phone simply cannot start one —
            a capability the desktop rail has always had. */}
        {onOpenSpike && (
          <li>
            <button
              type="button"
              onClick={onOpenSpike}
              className="flex min-h-[var(--ui-rail-btn)] w-full items-center gap-3 border-b border-border/15 px-[var(--ui-pad-x)] py-2 text-left hover:bg-hover"
            >
              <Zap className="h-5 w-5 shrink-0 text-faint" strokeWidth={1.75} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-[length:var(--ui-text-body)] text-primary">Spike</span>
                <span className="truncate text-[length:var(--ui-text-label)] text-faint">
                  Throwaway exploration — never lands
                </span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-faint" />
            </button>
          </li>
        )}
        <li>
          <button
            type="button"
            aria-label={`Theme: ${theme}`}
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className="flex min-h-[var(--ui-rail-btn)] w-full items-center gap-3 border-b border-border/15 px-[var(--ui-pad-x)] py-2 text-left hover:bg-hover"
          >
            <SunMoon className="h-5 w-5 shrink-0 text-faint" strokeWidth={1.75} />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-[length:var(--ui-text-body)] text-primary">Theme</span>
              <span className="truncate text-[length:var(--ui-text-label)] text-faint">
                {theme === 'dark' ? 'Dark — tap for light' : 'Light — tap for dark'}
              </span>
            </span>
          </button>
        </li>
        <li>
          <button
            type="button"
            onClick={() =>
              uiStore.openTab({
                target: { type: 'source', resource: 'manifest', name: 'manifest' },
                title: 'manifest.yaml',
              })
            }
            className="flex min-h-[var(--ui-rail-btn)] w-full items-center gap-3 border-b border-border/15 px-[var(--ui-pad-x)] py-2 text-left hover:bg-hover"
          >
            <FileCog className="h-5 w-5 shrink-0 text-faint" strokeWidth={1.75} />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-[length:var(--ui-text-body)] text-primary">Manifest</span>
              <span className="truncate text-[length:var(--ui-text-label)] text-faint">
                Read the .alc/ config
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-faint" />
          </button>
        </li>
      </ul>
    </div>
  )
}
