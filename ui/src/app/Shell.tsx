// Shell.tsx — The IDE grid: activity bar, tool window, tabs, bottom panel, status bar.
import { PanelBottom, PanelLeft } from 'lucide-react'
import { ActivityBar } from '../components/ActivityBar'
import { BottomPanel } from '../components/BottomPanel'
import { Resizer } from '../components/Resizer'
import { StatusBar } from '../components/StatusBar'
import { TabBar } from '../components/TabBar'
import { ToolWindow } from '../components/ToolWindow'
import { uiStore, useUiState } from './uiStore'
import { ExecBridge } from './ExecBridge'
import { TabContent } from './TabContent'

export function Shell({
  projectName,
  onOpenProjects,
}: {
  projectName: string
  onOpenProjects: () => void
}) {
  const ui = useUiState()

  return (
    <div className="flex h-full flex-col">
      <ExecBridge />
      <div className="flex min-h-0 flex-1">
        <ActivityBar onOpenProjects={onOpenProjects} />

        {ui.leftCollapsed ? (
          <button
            type="button"
            title="Show project tree"
            onClick={() => uiStore.toggleLeft()}
            className="flex w-6 shrink-0 items-start justify-center border-r border-border bg-panel pt-2 text-faint hover:text-primary"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
        ) : (
          <>
            <div style={{ width: ui.leftWidth }} className="flex shrink-0 flex-col border-r border-border">
              <div className="flex h-7 items-center justify-between border-b border-border bg-panel px-2 text-[11px] uppercase tracking-wide text-faint">
                <span>Project</span>
                <button
                  type="button"
                  title="Hide project tree"
                  onClick={() => uiStore.toggleLeft()}
                  className="text-faint hover:text-primary"
                >
                  <PanelLeft className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-hidden">
                <ToolWindow />
              </div>
            </div>
            <Resizer orientation="x" onResize={(d) => uiStore.setLeftWidth(uiStore.getState().leftWidth + d)} />
          </>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <TabBar />
          <div className="min-h-0 flex-1 overflow-hidden bg-base">
            <TabContent />
          </div>

          {ui.bottomCollapsed ? (
            <button
              type="button"
              title="Show bottom panel"
              onClick={() => uiStore.toggleBottom()}
              className="flex h-6 shrink-0 items-center gap-1.5 border-t border-border bg-panel px-3 text-[11px] text-faint hover:text-primary"
            >
              <PanelBottom className="h-3.5 w-3.5" />
              Console / Problems
            </button>
          ) : (
            <>
              <Resizer orientation="y" onResize={(d) => uiStore.setBottomHeight(uiStore.getState().bottomHeight - d)} />
              <div style={{ height: ui.bottomHeight }} className="shrink-0">
                <BottomPanel />
              </div>
            </>
          )}
        </div>
      </div>

      <StatusBar projectName={projectName} />
    </div>
  )
}
