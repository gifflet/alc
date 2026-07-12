// BottomPanel.tsx — Console (live exec output) + Problems (lint) tool panel.
import { ChevronDown, CircleCheck } from 'lucide-react'
import { useLint } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useExecState } from '../app/execStore'
import { uiStore, useUiState } from '../app/uiStore'
import { Console } from './Console'
import { EmptyState } from './EmptyState'
import { StatusDot } from './StatusDot'
import type { Tone } from './StatusDot'

const SEVERITY_TONE: Record<string, Tone> = { error: 'error', warning: 'warn', warn: 'warn' }

function ProblemsTab() {
  const id = useProjectId()
  const { data } = useLint(id)
  const violations = data?.violations ?? []
  if (violations.length === 0) {
    return <EmptyState icon={CircleCheck} message="No problems — policy gate is clean." />
  }
  return (
    <div className="h-full overflow-auto">
      {violations.map((v, i) => (
        <div
          key={i}
          className="flex items-start gap-2 border-b border-border/60 px-3 py-1.5 text-[12px]"
        >
          <span className="mt-1">
            <StatusDot tone={SEVERITY_TONE[v.severity] ?? 'warn'} />
          </span>
          <span className="font-mono text-[11px] text-faint">{v.rule}</span>
          <span className="text-muted">{v.message}</span>
        </div>
      ))}
    </div>
  )
}

function PanelTab({ id, label, count }: { id: 'console' | 'problems'; label: string; count?: number }) {
  const { bottomTab } = useUiState()
  const active = bottomTab === id
  return (
    <button
      type="button"
      onClick={() => uiStore.setBottomTab(id)}
      className={`relative px-3 py-1 text-[11px] uppercase tracking-wide transition-colors duration-120 ${
        active ? 'text-primary' : 'text-faint hover:text-muted'
      }`}
    >
      {active && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-accent" />}
      {label}
      {count !== undefined && count > 0 && <span className="ml-1 tabular text-faint">{count}</span>}
    </button>
  )
}

export function BottomPanel() {
  const id = useProjectId()
  const { bottomTab } = useUiState()
  const { data: lint } = useLint(id)
  const { execs } = useExecState()
  const running = execs.filter((e) => e.projectId === id && e.status === 'running').length
  return (
    <div className="flex h-full flex-col border-t border-border bg-panel">
      <div className="flex items-center border-b border-border">
        <PanelTab id="console" label="Console" count={running} />
        <PanelTab id="problems" label="Problems" count={lint?.violations.length} />
        <button
          type="button"
          aria-label="Collapse panel"
          onClick={() => uiStore.toggleBottom()}
          className="ml-auto flex h-6 w-6 items-center justify-center text-faint transition-colors duration-120 hover:text-primary"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        {bottomTab === 'console' ? <Console /> : <ProblemsTab />}
      </div>
    </div>
  )
}
