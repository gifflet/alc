// primitives.tsx — Small presentational helpers shared across views.
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Tone } from './StatusDot'

const PILL_TONE: Record<Tone, string> = {
  live: 'border-live/50 text-live',
  running: 'border-running/50 text-running',
  error: 'border-error/50 text-error',
  warn: 'border-warn/50 text-warn',
  idle: 'border-border text-faint',
  accent: 'border-accent/50 text-accent',
}

/** A compact status badge (success / failed / running …). */
export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-[3px] border px-1.5 py-0.5 font-mono text-[length:var(--ui-text-label)] uppercase tracking-wide ${PILL_TONE[tone]}`}
    >
      {children}
    </span>
  )
}

/** A dashboard card: titled surface with a header icon. */
export function Card({
  title,
  icon: Icon,
  action,
  children,
}: {
  title: string
  icon: LucideIcon
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="flex flex-col rounded-[var(--radius-md)] bg-raised shadow-[var(--elev-1)] ring-1 ring-border/40">
      <header className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2 text-[length:var(--ui-text-body)] font-medium text-primary">
          <Icon className="h-3.5 w-3.5 text-muted" strokeWidth={1.75} />
          {title}
        </div>
        {action}
      </header>
      <div className="flex-1 p-3">{children}</div>
    </section>
  )
}

/** A labelled numeric metric (scorecard / queue counts). */
export function Metric({ label, value, tone }: { label: string; value: ReactNode; tone?: Tone }) {
  const color =
    tone === 'live'
      ? 'text-live'
      : tone === 'error'
        ? 'text-error'
        : tone === 'running'
          ? 'text-running'
          : 'text-primary'
  return (
    <div className="flex flex-col gap-0.5">
      <span className={`tabular font-mono text-[18px] leading-none ${color}`}>{value}</span>
      <span className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">{label}</span>
    </div>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="p-4 text-[length:var(--ui-text-body)] text-muted">{label}</div>
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="m-3 rounded-panel border border-error/40 bg-error/10 px-3 py-2 text-[length:var(--ui-text-body)] text-error">
      {message}
    </div>
  )
}
