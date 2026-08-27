// ActionButton.tsx — One shape for "a button that starts something".
//
// Sixty-three of these were hand-written across the app in twenty-four distinct
// shapes: same role, different padding, different type size, some carrying the
// density floor and some not. Nothing enforced the difference, so nothing caught
// it when a class was silently dropped and a button lost its padding entirely.
//
// The tones are the ones already in use: accent starts work, live drains or
// runs, error destroys, ghost is everything else. Size is about type, not about
// the target — the floor is `--ui-control-h` in every case, which is what makes
// these tappable on a phone without a second thought at each call site.
import type { MouseEvent, ReactNode } from 'react'

const TONES = {
  accent: 'border-accent/60 bg-accent/10 text-accent hover:bg-accent/20',
  live: 'border-live/50 bg-live/10 text-live hover:bg-live/20',
  error: 'border-error/50 bg-error/5 text-error hover:bg-error/10',
  ghost: 'border-border text-muted hover:bg-hover hover:text-primary',
} as const

export function ActionButton({
  children,
  onClick,
  tone = 'ghost',
  size = 'md',
  disabled,
  type = 'button',
  className = '',
  'aria-label': ariaLabel,
  title,
}: {
  children: ReactNode
  /** Takes the event: a button inside a clickable row needs stopPropagation. */
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void
  tone?: keyof typeof TONES
  /** `sm` sits inside a dense row, `md` is the default, `lg` is for the one
   *  primary action on a screen — presence is the point, not just the target. */
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  type?: 'button' | 'submit'
  className?: string
  'aria-label'?: string
  title?: string
}) {
  const pad =
    size === 'sm' ? 'gap-1 px-2 py-1' : size === 'lg' ? 'gap-2 px-4 py-2' : 'gap-1.5 px-2.5 py-1.5'
  const text =
    size === 'sm' ? 'text-[length:var(--ui-text-label)]' : 'text-[length:var(--ui-text-body)]'
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      title={title}
      className={`flex min-h-[var(--ui-control-h)] items-center ${pad} ${text} rounded-panel border ${TONES[tone]} transition-colors duration-120 disabled:opacity-40 ${className}`}
    >
      {children}
    </button>
  )
}
