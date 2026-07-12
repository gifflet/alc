// EmptyState.tsx — A designed empty state: icon + one line + optional action.
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export function EmptyState({
  icon: Icon,
  message,
  action,
}: {
  icon: LucideIcon
  message: string
  action?: ReactNode
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
      <Icon className="h-6 w-6 text-faint" strokeWidth={1.5} />
      <p className="text-[12px] text-muted">{message}</p>
      {action}
    </div>
  )
}
