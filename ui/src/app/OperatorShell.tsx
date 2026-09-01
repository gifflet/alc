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
import { ChevronLeft, FolderTree, SquareTerminal } from 'lucide-react'
import { BottomPanel } from '../components/BottomPanel'
import { BottomTabBar } from '../components/BottomTabBar'
import { Mark } from '../components/Mark'
import { Sheet } from '../components/Sheet'
import { SpikeDialog } from '../views/SpikeDialog'
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
/** The four views that own a bottom tab. They are peers, not a stack: moving
 *  between them is switching channel, not travelling somewhere you came from. */
const RESIDENT = ['dashboard', 'inbox', 'fleet', 'queue']

export function destinationFor(activeTabId: string | null, moreOpen: boolean): string | null {
  if (moreOpen) return 'more'
  if (!activeTabId) return null
  const match = /^view:(.+)$/.exec(activeTabId)
  if (!match) return null
  return RESIDENT.includes(match[1]) ? match[1] : 'more'
}

/** Whether there is somewhere to go back TO.
 *
 *  Not `tabs.length > 1`. The phone has no tab bar, so every destination visited
 *  leaves an invisible tab behind: Inbox, Home, Inbox left two of them and a
 *  back arrow that never went away — and pressing it closed the destination the
 *  operator was looking at, which is not going back by any reading.
 *
 *  Back exists when you went INTO something: a run, a file, a review, or one of
 *  the views that live behind More. Between the four residents there is no back,
 *  because there was no forward. */
export function canGoBackFrom(activeTabId: string | null, moreOpen: boolean): boolean {
  if (moreOpen) return true
  if (!activeTabId) return false
  const match = /^view:(.+)$/.exec(activeTabId)
  return match ? !RESIDENT.includes(match[1]) : true
}

export function OperatorShell({
  projectName,
  onSwitchProject,
  onOpenProjects,
}: {
  projectName: string
  onSwitchProject: () => void
  // Shell has always passed this; the phone silently dropped it — which meant
  // a phone had NO path to the ProjectSelector at all: no register, no clone,
  // no new project. The junior operator who lives on the phone could not even
  // begin. Same disease the Spike row cured, same cure: a More entry.
  onOpenProjects: () => void
}) {
  const ui = useUiState()
  const projectId = useProjectId()
  const { data: inbox } = useInbox(projectId)
  const { status } = useWs()
  const [sheet, setSheet] = useState<SheetName>(null)
  const [moreOpen, setMoreOpen] = useState(false)
  const [spikeOpen, setSpikeOpen] = useState(false)

  const active = ui.tabs.find((t) => t.id === ui.activeTabId)
  const canGoBack = canGoBackFrom(ui.activeTabId, moreOpen)

  // Picking something in a sheet is navigation, and a sheet that survives it
  // covers the very thing it was used to reach — the tap reads as a no-op. Any
  // openTab while a sheet is up dismisses it. navSeq rather than activeTabId
  // because re-opening the tab already in front is still a choice the operator
  // made, and leaves the id unchanged.
  useEffect(() => {
    setSheet(null)
    // More has the same shape as a sheet and the same failure: it covers the
    // screen, and picking Metrics in it opened Metrics BEHIND it. The title
    // still said More, so the tap read as a no-op and the only way out was a
    // back arrow that looked like it would undo the choice.
    setMoreOpen(false)
  }, [ui.navSeq])

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
    if (!active) return
    if (ui.tabs.length > 1) {
      uiStore.closeTab(active.id)
      return
    }
    // Deep-linked straight into a run with nothing underneath. Closing would
    // leave an empty shell, so land on Home — the destination, not a void.
    openView('dashboard')
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
            {/* The mark, not a generic box. The phone header has 24px of slack —
                no room for a brand slot of its own — but this button was already
                here wearing an icon that said nothing about the app or about
                switching project. Same target, same action, and the one surface
                where the site and the app previously shared no mark at all. */}
            <Mark size={20} />
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
        {moreOpen ? <More onOpenSpike={() => setSpikeOpen(true)} onOpenProjects={onOpenProjects} /> : <TabContent />}
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

      {spikeOpen && <SpikeDialog onClose={() => setSpikeOpen(false)} />}
    </div>
  )
}
