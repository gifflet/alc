import Link from 'next/link'
import { getSections } from '@/lib/content'
import { MobileNav } from './MobileNav'
import { Mark } from './Logo'

/** Server component: the nav tree is read from disk once at build time and
 *  handed to the mobile sheet as data, so no filesystem code reaches the client. */
export function SiteHeader() {
  const sections = getSections().map((s) => ({
    label: s.label,
    pages: s.pages.map((p) => ({ href: p.href, title: p.title })),
  }))

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-base/85 backdrop-blur-md">
      <div className="mx-auto max-w-[1200px] px-4 h-14 flex items-center gap-4">
        <Link
          href="/"
          aria-label="ALC — home"
          className="group flex shrink-0 items-center gap-2.5 text-primary transition-colors hover:text-accent"
        >
          <Mark size={24} />
          <span className="text-[17px] font-semibold tracking-tight">ALC</span>
        </Link>

        {/* min-h-[44px] on each link, not padding on the nav: the target has to be
            the anchor itself, or the gap between links stays dead space. */}
        <nav aria-label="Main" className="ml-auto hidden md:flex items-center gap-2 text-sm">
          <Link href="/docs/getting-started/introduction" className="inline-flex min-h-[44px] items-center rounded-sm px-2.5 text-muted transition-colors hover:text-primary">
            Docs
          </Link>
          <Link href="/docs/concepts/control-plane" className="inline-flex min-h-[44px] items-center rounded-sm px-2.5 text-muted transition-colors hover:text-primary">
            Concepts
          </Link>
          <Link href="/docs/reference/cli" className="inline-flex min-h-[44px] items-center rounded-sm px-2.5 text-muted transition-colors hover:text-primary">
            CLI
          </Link>
          <Link
            href="/changelog"
            className="inline-flex min-h-[44px] items-center rounded-sm px-2.5 text-muted transition-colors hover:text-primary"
          >
            Changelog
          </Link>
          <a
            href="https://github.com/gifflet/alc"
            className="inline-flex min-h-[44px] items-center rounded-sm px-2.5 text-muted transition-colors hover:text-primary"
          >
            GitHub
          </a>
        </nav>

        <div className="ml-auto md:hidden">
          <MobileNav sections={sections} />
        </div>
      </div>
    </header>
  )
}
