// OperatorShell.tsx — The phone layout: decide, don't edit.
//
// The IDE grid does not apply below the narrow breakpoint (on a 411px device the
// tool window alone took ~55% of the width). This layout keeps the same routes,
// the same store and the same truth, scoped to what a phone is for: watch what
// is running, read why something failed, land or discard, re-enqueue, stop a
// loop.
//
// It deliberately introduces NO new navigation state: uiStore.tabs is already an
// ordered list with an activeTabId — a stack in all but name. Opening pushes,
// back pops, and tabRoute/urlSync keep owning the URL, so a link opened on the
// phone shows exactly what it shows on the desk.
import { useEffect, useState } from 'react'
import { Boxes, ChevronLeft, FolderTree, SquareTerminal } from 'lucide-react'
import { BottomPanel } from '../components/BottomPanel'
import { BottomTabBar } from '../components/BottomTabBar'
import { Sheet } from '../components/Sheet'
import { StatusDot } from '../components/StatusDot'
import { ToolWindow } from '../components/ToolWindow'
import { useInbox } from '../api/hooks'
import { useWs } from '../ws/WsProvider'
import { useProjectId } from './ProjectContext'
import { openView } from '../components/ActivityBar'
import { uiStore, useUiState } from './uiStore'
import type { PrimaryView } from './uiStore'
import { ExecBridge } from './ExecBridge'
import { TabContent } from './TabContent'
import { More } from '../views/More'

type SheetName = 'tree' | 'console' | null

/** The bottom-tab destination the active tab belongs to, or null. */
export function destinationFor(activeTabId: string | null, moreOpen: boolean): string | null {
  if (moreOpen) return 'more'
  if (!activeTabId) return null
  const match = /^view:(.+)$/.exec(activeTabId)
  if (!match) return null
  return ['dashboard', 'inbox', 'fleet', 'queue'].includes(match[1]) ? match[1] : 'more'
}

export function OperatorShell({
  projectName,
  onSwitchProject,
}: {
  projectName: string
  onSwitchProject: () => void
}) {
  const ui = useUiState()
  const projectId = useProjectId()
  const { data: inbox } = useInbox(projectId)
  const { status } = useWs()
  const [sheet, setSheet] = useState<SheetName>(null)
  const [moreOpen, setMoreOpen] = useState(false)

  const active = ui.tabs.find((t) => t.id === ui.activeTabId)
  const canGoBack = ui.tabs.length > 1 || moreOpen

  // Android's system back must feel native: close a sheet, then pop the stack,
  // and only then leave the app. Registered here only, so desktop history is
  // untouched.
  useEffect(() => {
    const onPop = (event: PopStateEvent) => {
      if (sheet) {
        event.preventDefault?.()
        setSheet(null)
        history.pushState(null, '', location.href)
        return
      }
      if (moreOpen) {
        setMoreOpen(false)
        history.pushState(null, '', location.href)
      }
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [sheet, moreOpen])

  const goBack = () => {
    if (moreOpen) {
      setMoreOpen(false)
      return
    }
    if (active && ui.tabs.length > 1) uiStore.closeTab(active.id)
  }

  const selectDestination = (view: PrimaryView | 'more') => {
    setSheet(null)
    if (view === 'more') {
      setMoreOpen(true)
      return
    }
    setMoreOpen(false)
    openView(view)
  }

  const title = moreOpen ? 'More' : (active?.title ?? projectName)

  return (
    <div className="flex h-full flex-col">
      <ExecBridge />

      <header className="flex min-h-[var(--ui-rail-btn)] shrink-0 items-center gap-1 border-b border-border bg-panel px-1">
        {canGoBack ? (
          <button
            type="button"
            aria-label="Back"
            onClick={goBack}
            className="flex h-[var(--ui-rail-btn)] w-[var(--ui-rail-btn)] items-center justify-center text-faint"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
        ) : (
          <button
            type="button"
            aria-label="Switch project"
            onClick={onSwitchProject}
            className="flex h-[var(--ui-rail-btn)] w-[var(--ui-rail-btn)] items-center justify-center text-faint"
          >
            <Boxes className="h-5 w-5" />
          </button>
        )}

        <span className="min-w-0 flex-1 truncate text-[length:var(--ui-text-title)] text-primary">
          {title}
        </span>

        <StatusDot
          tone={status === 'open' ? 'live' : 'warn'}
          pulse={status === 'connecting'}
          title={status === 'open' ? 'WebSocket open' : `WebSocket ${status}`}
        />
        <button
          type="button"
          aria-label="Project tree"
          onClick={() => setSheet('tree')}
          className="flex h-[var(--ui-rail-btn)] w-[var(--ui-rail-btn)] items-center justify-center text-faint"
        >
          <FolderTree className="h-5 w-5" />
        </button>
        <button
          type="button"
          aria-label="Console"
          onClick={() => setSheet('console')}
          className="flex h-[var(--ui-rail-btn)] w-[var(--ui-rail-btn)] items-center justify-center text-faint"
        >
          <SquareTerminal className="h-5 w-5" />
        </button>
      </header>

      <main className="min-h-0 flex-1 overflow-hidden bg-base">
        {moreOpen ? <More /> : <TabContent />}
      </main>

      <BottomTabBar
        active={destinationFor(ui.activeTabId, moreOpen)}
        onSelect={selectDestination}
        inboxCount={inbox?.count}
      />

      {sheet === 'tree' && (
        <Sheet title="Project" onClose={() => setSheet(null)}>
          <ToolWindow />
        </Sheet>
      )}
      {sheet === 'console' && (
        <Sheet title="Console / Problems" onClose={() => setSheet(null)}>
          <div className="h-[50vh]">
            <BottomPanel />
          </div>
        </Sheet>
      )}
    </div>
  )
}
