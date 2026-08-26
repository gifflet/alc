import Link from 'next/link'

export default function NotFound() {
  return (
    <div className="mx-auto max-w-[1200px] px-4 py-24 text-center">
      <p className="font-mono text-sm text-faint">404</p>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight">This page does not exist</h1>
      <p className="mt-2.5 text-muted">
        It may have been renamed, or the link may be stale.
      </p>
      <Link
        href="/docs"
        className="mt-6 inline-flex min-h-[44px] items-center rounded-md border border-border px-4 text-sm text-primary transition-colors hover:border-faint"
      >
        Go to the documentation
      </Link>
    </div>
  )
}
