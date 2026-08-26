'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

type NavSection = { label: string; pages: { href: string; title: string }[] }

export function Sidebar({ sections }: { sections: NavSection[] }) {
  const pathname = usePathname()
  return (
    <nav aria-label="Documentation" className="flex flex-col gap-7 text-sm">
      {sections.map((section) => (
        <div key={section.label}>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-faint">
            {section.label}
          </p>
          <ul className="flex flex-col border-l border-border">
            {section.pages.map((page) => {
              const active = pathname === page.href
              return (
                <li key={page.href}>
                  <Link
                    href={page.href}
                    aria-current={active ? 'page' : undefined}
                    className={
                      'block -ml-px border-l py-1.5 pl-3 transition-colors ' +
                      (active
                        ? 'border-accent text-accent font-medium'
                        : 'border-transparent text-muted hover:border-faint hover:text-primary')
                    }
                  >
                    {page.title}
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </nav>
  )
}
