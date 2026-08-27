// Dialog.tsx — Modal shell + a confirm dialog, styled like the project selector.
//
// In-app modals (never native alert/confirm) so the control room keeps its look
// and never blocks the event loop. Escape and backdrop click both close.
import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export function Dialog({
  title,
  onClose,
  children,
  footer,
  width = 460,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  width?: number
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={title}
        // `width` is a ceiling, not a fixed size: at 520px on a 411px phone a
        // fixed width overflows the viewport. Full width up to the ceiling keeps
        // the desktop identical and makes every dialog fit a phone.
        style={{ width: '100%', maxWidth: width }}
        className="flex max-h-[80vh] flex-col rounded-[var(--radius-lg)] bg-panel shadow-[var(--elev-3)] ring-1 ring-border/50"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-border px-3 py-2">
          <h2 className="text-[length:var(--ui-text-title)] font-medium text-primary">{title}</h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint hover:text-primary"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-3">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-border p-3">{footer}</div>
        )}
      </div>
    </div>
  )
}

/** A primary / danger action button used inside dialog footers. */
export function DialogButton({
  children,
  onClick,
  tone = 'accent',
  disabled,
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  tone?: 'accent' | 'error' | 'ghost'
  disabled?: boolean
  type?: 'button' | 'submit'
}) {
  const styles =
    tone === 'error'
      ? 'border-error/60 bg-error/10 text-error hover:bg-error/20'
      : tone === 'ghost'
        ? 'border-border text-muted hover:bg-hover hover:text-primary'
        : 'border-accent/60 bg-accent/10 text-accent hover:bg-accent/20'
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex min-h-[var(--ui-control-h)] items-center rounded-panel border px-3 text-[length:var(--ui-text-body)] transition-colors duration-120 disabled:opacity-40 ${styles}`}
    >
      {children}
    </button>
  )
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel = 'Confirm',
  tone = 'error',
  onConfirm,
  onCancel,
}: {
  title: string
  message: ReactNode
  confirmLabel?: string
  tone?: 'accent' | 'error'
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Dialog
      title={title}
      onClose={onCancel}
      footer={
        <>
          <DialogButton tone="ghost" onClick={onCancel}>
            Cancel
          </DialogButton>
          <DialogButton tone={tone} onClick={onConfirm}>
            {confirmLabel}
          </DialogButton>
        </>
      }
    >
      <div className="text-[length:var(--ui-text-body)] text-muted">{message}</div>
    </Dialog>
  )
}
