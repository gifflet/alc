// TabBar.tsx — Center editor tabs; active tab underlined with the accent.
import { X } from 'lucide-react'
import { uiStore, useUiState } from '../app/uiStore'

export function TabBar() {
  const { tabs, activeTabId } = useUiState()
  if (tabs.length === 0) return null
  return (
    <div className="flex h-8 shrink-0 items-stretch overflow-x-auto border-b border-border bg-panel">
      {tabs.map((tab) => {
        const active = tab.id === activeTabId
        return (
          <div
            key={tab.id}
            onClick={() => uiStore.setActiveTab(tab.id)}
            className={`group relative flex cursor-pointer items-center gap-2 whitespace-nowrap border-r border-border px-3 text-[12px] transition-colors duration-120 ${
              active ? 'bg-raised text-primary' : 'text-muted hover:bg-hover'
            }`}
          >
            {active && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-accent" />}
            <span className="truncate">{tab.title}</span>
            {tab.closable && (
              <button
                type="button"
                aria-label={`Close ${tab.title}`}
                onClick={(e) => {
                  e.stopPropagation()
                  uiStore.closeTab(tab.id)
                }}
                className="flex h-4 w-4 items-center justify-center rounded text-faint opacity-0 transition-opacity duration-120 hover:bg-hover hover:text-primary group-hover:opacity-100"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
