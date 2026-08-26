import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { getRelease, getReleases, formatDate } from '@/lib/changelog'
import type { Entry } from '@/lib/changelog'
import { SITE } from '@/lib/site'

type Params = { version: string }

export async function generateStaticParams(): Promise<Params[]> {
  return (await getReleases()).map((r) => ({ version: r.slug }))
}

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>
}): Promise<Metadata> {
  const { version } = await params
  const r = await getRelease(version)
  if (!r) return {}
  const title = r.headline ?? `Version ${r.version}`
  return {
    title: `${r.version} — ${title}`,
    description: title,
    alternates: { canonical: `/changelog/${r.slug}` },
    openGraph: { type: 'article', title, publishedTime: r.date, siteName: SITE.name },
  }
}

function Group({ title, entries }: { title: string; entries: Entry[] }) {
  if (entries.length === 0) return null
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <ul className="mt-4 flex flex-col gap-3">
        {entries.map((e) => (
          <li key={e.text} className="flex gap-3 leading-relaxed text-muted">
            <span aria-hidden className="mt-[10px] h-1.5 w-1.5 shrink-0 rounded-full bg-border" />
            <span>
              {e.scope && (
                <span className="mr-2 font-mono text-[13px] text-faint">{e.scope}</span>
              )}
              {e.text}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default async function ReleasePage({ params }: { params: Promise<Params> }) {
  const { version } = await params
  const r = await getRelease(version)
  if (!r) notFound()

  return (
    <div className="mx-auto max-w-[760px] px-4 py-14">
      <Link
        href="/changelog"
        className="inline-flex min-h-[44px] items-center gap-2 text-sm text-muted transition-colors hover:text-primary"
      >
        <ArrowLeft size={15} />
        Changelog
      </Link>

      <header className="mt-4">
        <div className="flex flex-wrap items-center gap-3">
          <time dateTime={r.date} className="font-mono text-sm text-faint">
            {formatDate(r.date)}
          </time>
          <span className="rounded-xs border border-border bg-panel px-2 py-0.5 font-mono text-xs text-muted">
            {r.version}
          </span>
        </div>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-balance">
          {r.headline ?? `Version ${r.version}`}
        </h1>
      </header>

      <Group title="Features" entries={r.features} />
      <Group title="Fixes" entries={r.fixes} />
      <Group title="Other changes" entries={r.other} />

      {r.features.length + r.fixes.length + r.other.length === 0 && (
        <p className="mt-10 text-muted">
          No categorised changes recorded for this release.
        </p>
      )}

      <footer className="mt-14 flex flex-wrap gap-2 border-t border-border pt-4 text-sm">
        <a
          href={`${SITE.repo}/releases/tag/v${r.version}`}
          className="inline-flex min-h-[44px] items-center rounded-sm px-2 text-accent underline underline-offset-4"
        >
          Release on GitHub
        </a>
        <a
          href={`${SITE.pypi}${r.version}/`}
          className="inline-flex min-h-[44px] items-center rounded-sm px-2 text-accent underline underline-offset-4"
        >
          Package on PyPI
        </a>
      </footer>
    </div>
  )
}
