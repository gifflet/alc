// Landing primitives — layout only, no copy.
//
// The words live in content/landing.mdx and are passed in as props, so the
// writing stays reviewable as prose in one file rather than being scattered
// across JSX. These components decide rhythm and hierarchy; they never decide
// what is said.
import type { ReactNode } from 'react'

export function Section({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`mx-auto max-w-[1200px] px-4 py-16 md:py-24 ${className}`}>
      {children}
    </section>
  )
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="mb-3 font-mono text-[11px] uppercase tracking-[0.14em] text-faint">{children}</p>
  )
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="text-2xl md:text-3xl font-semibold tracking-tight text-balance">{children}</h2>
  )
}

export function Lede({ children }: { children: ReactNode }) {
  return <p className="mt-3 max-w-2xl text-muted leading-relaxed text-pretty">{children}</p>
}

/** A terminal-styled block. Presentational: the traffic lights are decorative
 *  and hidden from assistive tech, and the command itself stays selectable
 *  text so it can be copied. */
export function Terminal({ lines }: { lines: { cmd: string; note?: string }[] }) {
  return (
    <div className="overflow-hidden rounded-md border border-border bg-panel shadow-[var(--elev-1)]">
      <div aria-hidden className="flex items-center gap-1.5 border-b border-border px-3.5 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-error/60" />
        <span className="h-2.5 w-2.5 rounded-full bg-warn/60" />
        <span className="h-2.5 w-2.5 rounded-full bg-live/60" />
      </div>
      {/* Lines wrap instead of scrolling. A horizontal scroller inside a hero
          hides content behind an affordance nobody looks for on a phone — the
          first capture at 411px cut "…export endp" with nothing to suggest more
          existed. A real terminal wraps too, so this is also the honest shape.
          The negative indent hangs the continuation under the command rather
          than under the prompt. */}
      <div className="p-4 font-mono text-[12px] leading-relaxed sm:text-[13px]">
        {lines.map((line) => (
          <div key={line.cmd} className="whitespace-pre-wrap break-words pl-[1.2em] -indent-[1.2em]">
            <span className="select-none text-faint">$ </span>
            <span className="text-primary">{line.cmd}</span>
            {line.note && <span className="text-faint">  # {line.note}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

export function Card({
  title,
  children,
  icon,
}: {
  title: string
  children: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="rounded-md border border-border bg-panel p-5 transition-colors hover:border-faint">
      {icon && <div className="mb-3 text-accent">{icon}</div>}
      <h3 className="font-medium text-primary">{title}</h3>
      <p className="mt-1.5 text-sm leading-relaxed text-muted">{children}</p>
    </div>
  )
}

/** A row that breaks out of the container. `w-screen` plus a negative margin
 *  from the 50% line is the one technique that stays centred regardless of the
 *  container's own width, and it does not depend on knowing the viewport. The
 *  scrollbar is excluded via 100vw vs 100% so the page never gains a horizontal
 *  scroll on Windows, where the scrollbar takes real width. */
export function Bleed({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`relative left-1/2 right-1/2 -mx-[50vw] w-[100vw] max-w-[100vw] ${className}`}
      style={{ marginLeft: '-50vw', marginRight: '-50vw' }}
    >
      {children}
    </div>
  )
}

/** Wide but still bounded — for media that should dominate without touching
 *  the screen edges on a large display. */
export function WideRow({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto w-full max-w-[1360px] ${className}`}>{children}</div>
}
