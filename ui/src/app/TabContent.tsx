// TabContent.tsx — Render the active tab's view. The tab bar drives navigation.
import { PanelsTopLeft } from 'lucide-react'
import { EmptyState } from '../components/EmptyState'
import { Dashboard } from '../views/Dashboard'
import { Queue } from '../views/Queue'
import { Runs } from '../views/Runs'
import { RunDetail } from '../views/RunDetail'
import { Loops } from '../views/Loops'
import { LoopDetail } from '../views/LoopDetail'
import { Conduct } from '../views/Conduct'
import { RunConfigs } from '../views/RunConfigs'
import { SourceEditor } from '../views/SourceEditor'
import { Team } from '../views/Team'
import { useUiState } from './uiStore'
import type { PrimaryView, Tab } from './uiStore'

const VIEWS: Record<PrimaryView, () => React.ReactElement> = {
  dashboard: Dashboard,
  queue: Queue,
  runs: Runs,
  loops: Loops,
  conduct: Conduct,
  'run-configs': RunConfigs,
  team: Team,
}

function renderTab(tab: Tab): React.ReactElement {
  const t = tab.target
  switch (t.type) {
    case 'view': {
      const View = VIEWS[t.view]
      return <View />
    }
    case 'run':
      return <RunDetail stem={t.stem} />
    case 'loop':
      return <LoopDetail name={t.name} />
    case 'source':
      return <SourceEditor resource={t.resource} name={t.name} />
  }
}

export function TabContent() {
  const { tabs, activeTabId } = useUiState()
  const active = tabs.find((t) => t.id === activeTabId)
  if (!active) {
    return (
      <EmptyState
        icon={PanelsTopLeft}
        message="Open a view from the activity bar, or a file from the project tree."
      />
    )
  }
  // Keyed by tab id so each tab keeps its own component state while open.
  return <div key={active.id} className="h-full min-h-0">{renderTab(active)}</div>
}
