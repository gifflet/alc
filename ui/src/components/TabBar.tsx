// TabBar.tsx — Center editor tabs; active tab underlined with the accent.
//
// A tab with unsaved edits shows a dirty dot in place of the close affordance
// (IntelliJ-style); the dot fades to the close button on hover, and closing a
// dirty tab asks for confirmation so typed content is never lost silently.
import { useState } from 'react'
import { X } from 'lucide-react'
import { ConfirmDialog } from './Dialog'
import { uiStore, useUiState } from '../app/uiStore'

export function TabBar() {
  const { tabs, activeTabId, dirty } = useUiState()
  const [pendingClose, setPendingClose] = useState<string | null>(null)
  if (tabs.length === 0) return null

  const requestClose = (id: string) => {
    if (dirty[id]) setPendingClose(id)
    else uiStore.closeTab(id)
  }

  return (
    <div className="flex h-8 shrink-0 items-stretch overflow-x-auto border-b border-border bg-panel">
      {tabs.map((tab) => {
        const active = tab.id === activeTabId
        const isDirty = Boolean(dirty[tab.id])
        return (
          <div
            key={tab.id}
            onClick={() => uiStore.setActiveTab(tab.id)}
            className={`group relative flex cursor-pointer items-center gap-2 whitespace-nowrap border-r border-border px-3 text-[length:var(--ui-text-body)] transition-colors duration-120 ${
              active ? 'bg-raised text-primary' : 'text-muted hover:bg-hover'
            }`}
          >
            {active && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-accent" />}
            <span className="truncate">{tab.title}</span>
            {tab.closable && (
              <span className="relative flex h-4 w-4 items-center justify-center">
                {isDirty && (
                  <span className="pointer-events-none h-1.5 w-1.5 rounded-full bg-muted transition-opacity duration-120 group-hover:opacity-0" />
                )}
                <button
                  type="button"
                  aria-label={`Close ${tab.title}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    requestClose(tab.id)
                  }}
                  className="absolute inset-0 flex items-center justify-center rounded text-faint alc-reveal hover:bg-hover hover:text-primary"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            )}
          </div>
        )
      })}

      {pendingClose && (
        <ConfirmDialog
          title="Discard changes?"
          message="This file has unsaved changes. Closing the tab will discard them."
          confirmLabel="Discard"
          onConfirm={() => {
            uiStore.closeTab(pendingClose)
            setPendingClose(null)
          }}
          onCancel={() => setPendingClose(null)}
        />
      )}
    </div>
  )
}
