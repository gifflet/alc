// ConsolePane.tsx — Live monospaced console with auto-scroll (pauses on interaction).
//
// Auto-scrolls to the newest line unless the operator has scrolled up or is
// hovering the pane, so reading back through output is never yanked away.
import { useEffect, useRef, useState } from 'react'

export function ConsolePane({ lines }: { lines: string[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const [paused, setPaused] = useState(false)
  const hovering = useRef(false)

  function nearBottom(el: HTMLDivElement): boolean {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 24
  }

  useEffect(() => {
    const el = ref.current
    if (el && !paused) el.scrollTop = el.scrollHeight
  }, [lines, paused])

  return (
    <div
      ref={ref}
      onScroll={() => {
        const el = ref.current
        if (el) setPaused(hovering.current && !nearBottom(el))
      }}
      onMouseEnter={() => {
        hovering.current = true
      }}
      onMouseLeave={() => {
        hovering.current = false
        setPaused(false)
      }}
      className="h-full overflow-auto bg-base px-3 py-2 font-mono text-[length:var(--ui-text-body)] leading-[1.5] text-primary"
    >
      {lines.length === 0 ? (
        <span className="text-faint">No output.</span>
      ) : (
        lines.map((line, i) => (
          <div key={i} className="whitespace-pre-wrap break-words">
            {line || ' '}
          </div>
        ))
      )}
    </div>
  )
}
