// BottomPanel.tsx — Console (live exec output) + Problems (lint) tool panel.
import { ChevronDown, CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useLint } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useExecState } from '../app/execStore'
import { uiStore, useUiState } from '../app/uiStore'
import { violationTarget } from '../app/violations'
import type { Violation } from '../api/types'
import { Console } from './Console'
import { EmptyState } from './EmptyState'

/** Icon + colour class per severity; the colours come from the theme tokens
 * (--color-error / --color-warn), never from a literal here. */
function severityStyle(severity: string): { Icon: LucideIcon; color: string } {
  return severity === 'error'
    ? { Icon: CircleAlert, color: 'text-error' }
    : { Icon: TriangleAlert, color: 'text-warn' }
}

/** Number of error-severity violations — drives the Problems badge. */
function errorCount(violations: Violation[]): number {
  return violations.filter((v) => v.severity === 'error').length
}

function ProblemRow({ v }: { v: Violation }) {
  const { Icon, color } = severityStyle(v.severity)
  const target = violationTarget(v)
  const body = (
    <>
      <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${color}`} />
      <span className="shrink-0 font-mono text-[length:var(--ui-text-label)] text-faint">{v.rule}</span>
      <span className="text-muted">{v.message}</span>
    </>
  )
  if (!target) {
    return <div className="flex items-start gap-2 px-3 py-1.5 text-[length:var(--ui-text-body)]">{body}</div>
  }
  return (
    <button
      type="button"
      title={`Open ${target.title}`}
      onClick={() => uiStore.openTab(target)}
      className="flex w-full items-start gap-2 px-3 py-1.5 text-left text-[length:var(--ui-text-body)] transition-colors duration-120 hover:bg-hover"
    >
      {body}
    </button>
  )
}

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
        <div key={i} className="border-b border-border/15">
          <ProblemRow v={v} />
        </div>
      ))}
    </div>
  )
}

function PanelTab({
  id,
  label,
  count,
  badgeTone,
}: {
  id: 'console' | 'problems'
  label: string
  count?: number
  badgeTone?: 'faint' | 'error'
}) {
  const { bottomTab } = useUiState()
  const active = bottomTab === id
  return (
    <button
      type="button"
      onClick={() => uiStore.setBottomTab(id)}
      className={`relative px-3 py-1 text-[length:var(--ui-text-label)] uppercase tracking-wide transition-colors duration-120 ${
        active ? 'text-primary' : 'text-faint hover:text-muted'
      }`}
    >
      {active && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-accent" />}
      {label}
      {count !== undefined && count > 0 && (
        <span className={`ml-1 tabular ${badgeTone === 'error' ? 'text-error' : 'text-faint'}`}>
          {count}
        </span>
      )}
    </button>
  )
}

export function BottomPanel() {
  const id = useProjectId()
  const { bottomTab } = useUiState()
  const { data: lint } = useLint(id)
  const { execs } = useExecState()
  const running = execs.filter((e) => e.projectId === id && e.status === 'running').length
  const errors = errorCount(lint?.violations ?? [])
  return (
    <div className="flex h-full flex-col border-t border-border bg-panel">
      <div className="flex items-center border-b border-border">
        <PanelTab id="console" label="Console" count={running} />
        <PanelTab id="problems" label="Problems" count={errors} badgeTone="error" />
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
