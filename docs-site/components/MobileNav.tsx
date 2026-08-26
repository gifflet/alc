'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import * as Dialog from '@radix-ui/react-dialog'
import { Menu, X } from 'lucide-react'

type NavSection = { label: string; pages: { href: string; title: string }[] }

/** The full docs tree in a sheet. Radix handles focus trapping, scroll locking
 *  and Escape; the only thing left to own is closing on navigation, which a
 *  route change does not do by itself. */
export function MobileNav({ sections }: { sections: NavSection[] }) {
  const [open, setOpen] = useState(false)
  const pathname = usePathname()

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          aria-label="Open navigation"
          className="grid h-10 w-10 place-items-center rounded-sm text-muted hover:text-primary hover:bg-hover transition-colors"
        >
          <Menu size={18} />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 w-[86%] max-w-sm overflow-y-auto border-l border-border bg-panel p-5 shadow-[var(--elev-2)]">
          <div className="flex items-center justify-between mb-5">
            <Dialog.Title className="text-sm font-semibold">Documentation</Dialog.Title>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Close navigation"
                className="grid h-10 w-10 place-items-center rounded-sm text-muted hover:text-primary hover:bg-hover transition-colors"
              >
                <X size={18} />
              </button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">
            Links to every page in the ALC documentation.
          </Dialog.Description>
          <nav aria-label="Documentation" className="flex flex-col gap-6">
            {sections.map((section) => (
              <div key={section.label}>
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-faint">
                  {section.label}
                </p>
                <ul className="flex flex-col">
                  {section.pages.map((page) => {
                    const active = pathname === page.href
                    return (
                      <li key={page.href}>
                        <Link
                          href={page.href}
                          onClick={() => setOpen(false)}
                          aria-current={active ? 'page' : undefined}
                          className={
                            'flex min-h-[44px] items-center rounded-sm px-2 text-sm transition-colors ' +
                            (active
                              ? 'bg-accent/12 text-accent font-medium'
                              : 'text-muted hover:bg-hover hover:text-primary')
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
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
