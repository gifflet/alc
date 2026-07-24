// ActivityBar.tsx — The 40px icon rail: primary views + the projects action.
import {
  Boxes,
  GitCompare,
  LayoutDashboard,
  LineChart,
  ListTodo,
  Radio,
  RefreshCw,
  Settings,
  SlidersHorizontal,
  Users,
  Wand2,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { uiStore, useUiState } from '../app/uiStore'
import type { PrimaryView } from '../app/uiStore'

interface Item {
  view: PrimaryView
  icon: LucideIcon
  label: string
}

const ITEMS: Item[] = [
  { view: 'dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { view: 'queue', icon: ListTodo, label: 'Queue' },
  { view: 'runs', icon: Radio, label: 'Runs' },
  { view: 'loops', icon: RefreshCw, label: 'Loops' },
  { view: 'conduct', icon: Wand2, label: 'Conduct' },
  { view: 'team', icon: Users, label: 'Team' },
  { view: 'metrics', icon: LineChart, label: 'Metrics' },
  { view: 'compare', icon: GitCompare, label: 'Compare' },
  { view: 'run-configs', icon: SlidersHorizontal, label: 'Run Configurations' },
]

const VIEW_TITLE: Record<PrimaryView, string> = {
  dashboard: 'Dashboard',
  queue: 'Queue',
  runs: 'Runs',
  loops: 'Loops',
  conduct: 'Conduct',
  'run-configs': 'Run Configurations',
  team: 'Team',
  metrics: 'Metrics',
  compare: 'Compare',
}

export function openView(view: PrimaryView): void {
  uiStore.openTab({ target: { type: 'view', view }, title: VIEW_TITLE[view], closable: false })
}

function RailButton({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: LucideIcon
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={`relative flex h-10 w-10 items-center justify-center transition-colors duration-120 ${
        active ? 'text-primary' : 'text-faint hover:text-muted'
      }`}
    >
      {active && <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded bg-accent" />}
      <Icon className="h-5 w-5" strokeWidth={1.75} />
    </button>
  )
}

export function ActivityBar({
  onOpenProjects,
  onOpenSpike,
}: {
  onOpenProjects: () => void
  onOpenSpike: () => void
}) {
  const { activeTabId } = useUiState()
  return (
    <nav className="flex w-10 shrink-0 flex-col items-center justify-between border-r border-border bg-panel py-1">
      <div className="flex flex-col">
        {ITEMS.map((item) => (
          <RailButton
            key={item.view}
            icon={item.icon}
            label={item.label}
            active={activeTabId === `view:${item.view}`}
            onClick={() => openView(item.view)}
          />
        ))}
        <RailButton
          icon={Settings}
          label="Config — manifest"
          active={activeTabId === 'source:manifest:manifest'}
          onClick={() =>
            uiStore.openTab({
              target: { type: 'source', resource: 'manifest', name: 'manifest' },
              title: 'manifest.yaml',
            })
          }
        />
        <RailButton icon={Zap} label="Spike" active={false} onClick={onOpenSpike} />
      </div>
      <RailButton icon={Boxes} label="Projects" active={false} onClick={onOpenProjects} />
    </nav>
  )
}
