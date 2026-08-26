// Sheet.tsx — A dismissible bottom sheet, the mobile stand-in for a tool window.
//
// The IDE's side and bottom panels have nowhere to live on a 411px screen, so on
// mobile they become sheets: summoned, used, dismissed. Focus is trapped while
// open and returned on close, and Escape/back both close it.
import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'

export function Sheet({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const restoreRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    restoreRef.current = document.activeElement as HTMLElement | null
    panelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      // Returning focus is what makes a sheet usable with a keyboard or a
      // screen reader; without it focus falls back to <body>.
      restoreRef.current?.focus?.()
    }
  }, [onClose])

  return (
    <div className="fixed inset-0 z-40 flex flex-col justify-end bg-black/50" onClick={onClose}>
      <div
        ref={panelRef}
        role="dialog"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[75vh] flex-col rounded-t-[var(--radius-lg)] bg-panel pb-[env(safe-area-inset-bottom)] shadow-[var(--elev-3)] outline-none"
      >
        <div className="flex min-h-[var(--ui-control-h)] shrink-0 items-center justify-between border-b border-border px-[var(--ui-pad-x)] py-1">
          <h2 className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
            {title}
          </h2>
          <button
            type="button"
            aria-label={`Close ${title}`}
            onClick={onClose}
            className="flex h-[var(--ui-control-h)] w-[var(--ui-control-h)] items-center justify-center text-faint hover:text-primary"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">{children}</div>
      </div>
    </div>
  )
}
