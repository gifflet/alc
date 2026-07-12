// Resizer.tsx — A 1px drag handle that reports incremental pointer deltas.
//
// The parent applies each delta to the live panel size (read fresh from the
// store), so drags stay accurate and the size persists via the store.
import { useRef } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'

export function Resizer({
  orientation,
  onResize,
}: {
  orientation: 'x' | 'y'
  onResize: (delta: number) => void
}) {
  const last = useRef(0)

  function onPointerDown(e: ReactPointerEvent) {
    e.preventDefault()
    last.current = orientation === 'x' ? e.clientX : e.clientY
    const onMove = (ev: PointerEvent) => {
      const cur = orientation === 'x' ? ev.clientX : ev.clientY
      onResize(cur - last.current)
      last.current = cur
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      document.body.style.userSelect = ''
    }
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const cursor = orientation === 'x' ? 'cursor-col-resize' : 'cursor-row-resize'
  const size = orientation === 'x' ? 'w-1 h-full' : 'h-1 w-full'
  return (
    <div
      role="separator"
      onPointerDown={onPointerDown}
      className={`${size} ${cursor} shrink-0 bg-border/40 transition-colors duration-120 hover:bg-accent`}
    />
  )
}
