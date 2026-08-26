'use client'

import { useEffect, useState } from 'react'

type Heading = { id: string; text: string; depth: 2 | 3 }

/** Highlights the section currently in view. rootMargin pulls the observation
 *  band to the top of the viewport, so a heading counts as "current" once it
 *  reaches the top rather than when it merely becomes visible — otherwise every
 *  heading on a short page is active at once. */
export function TableOfContents({ headings }: { headings: Heading[] }) {
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => {
    if (headings.length === 0) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting)
        if (visible.length > 0) setActiveId(visible[0].target.id)
      },
      { rootMargin: '-80px 0px -70% 0px', threshold: 0 },
    )
    for (const h of headings) {
      const el = document.getElementById(h.id)
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
  }, [headings])

  if (headings.length < 2) return null

  return (
    <nav aria-label="On this page" className="text-sm">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-faint">
        On this page
      </p>
      <ul className="flex flex-col">
        {headings.map((h) => (
          <li key={h.id} className={h.depth === 3 ? 'pl-3' : undefined}>
            <a
              href={`#${h.id}`}
              className={
                'block min-h-[24px] py-1 leading-snug transition-colors ' +
                (activeId === h.id ? 'text-accent' : 'text-faint hover:text-primary')
              }
            >
              {h.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}
