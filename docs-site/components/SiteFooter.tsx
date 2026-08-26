import Link from 'next/link'

export function SiteFooter() {
  return (
    <footer className="border-t border-border mt-16">
      <div className="mx-auto max-w-[1200px] px-4 py-8 flex flex-wrap items-center justify-between gap-4 text-sm">
        <p className="text-faint">
          ALC is experimental, and honest about it — every feature ships with a hermetic test suite.
        </p>
        <div className="flex items-center gap-1">
          <Link href="/docs/getting-started/introduction" className="inline-flex min-h-[44px] items-center rounded-sm px-2.5 text-muted transition-colors hover:text-primary">
            Docs
          </Link>
          <a
            href="https://github.com/gifflet/alc"
            className="inline-flex min-h-[44px] items-center rounded-sm px-2.5 text-muted transition-colors hover:text-primary"
          >
            GitHub
          </a>
          <a
            href="https://pypi.org/project/alc-runtime/"
            className="inline-flex min-h-[44px] items-center rounded-sm px-2.5 text-muted transition-colors hover:text-primary"
          >
            PyPI
          </a>
        </div>
      </div>
    </footer>
  )
}
