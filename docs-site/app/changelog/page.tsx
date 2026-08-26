import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import { getReleases, formatDate } from '@/lib/changelog'
import { SITE } from '@/lib/site'

export const metadata: Metadata = {
  title: 'Changelog',
  description: `Every release of ${SITE.name}, what shipped in it, and when.`,
  alternates: { canonical: '/changelog' },
}

export default async function ChangelogIndex() {
  const releases = await getReleases()

  return (
    <div className="mx-auto max-w-[860px] px-4 py-14">
      <header className="mb-14">
        <h1 className="text-4xl font-semibold tracking-tight">Changelog</h1>
        <p className="mt-3 text-lg leading-relaxed text-muted">
          Every release, drawn from the commits that produced it. Versions follow the package on{' '}
          <a href={SITE.pypi} className="text-accent underline underline-offset-4">
            PyPI
          </a>
          .
        </p>
      </header>

      {releases.length === 0 ? (
        // The build reaches GitHub for this. If it could not, say so plainly and
        // point at the source rather than rendering an empty page that implies
        // nothing has ever shipped.
        <p className="text-muted">
          Release history is unavailable right now —{' '}
          <a href={`${SITE.repo}/releases`} className="text-accent underline underline-offset-4">
            read it on GitHub
          </a>
          .
        </p>
      ) : (
        <ol className="flex flex-col">
          {releases.map((r) => {
            const bullets = [...r.features, ...r.fixes].slice(0, 3)
            const rest = r.features.length + r.fixes.length + r.other.length - bullets.length
            return (
              <li key={r.slug} className="border-t border-border py-9 first:border-t-0 first:pt-0">
                <div className="flex flex-wrap items-center gap-3">
                  <time dateTime={r.date} className="font-mono text-sm text-faint">
                    {formatDate(r.date)}
                  </time>
                  <span className="rounded-xs border border-border bg-panel px-2 py-0.5 font-mono text-xs text-muted">
                    {r.version}
                  </span>
                </div>

                <h2 className="mt-3 text-xl font-semibold tracking-tight text-balance">
                  <Link href={`/changelog/${r.slug}`} className="hover:text-accent transition-colors">
                    {r.headline ?? `Version ${r.version}`}
                  </Link>
                </h2>

                {bullets.length > 0 && (
                  <ul className="mt-4 flex flex-col gap-2">
                    {bullets.map((e) => (
                      <li key={e.text} className="flex gap-2.5 text-[15px] leading-relaxed text-muted">
                        <span
                          aria-hidden
                          className={`mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full ${
                            e.kind === 'feat' ? 'bg-live' : 'bg-accent'
                          }`}
                        />
                        <span>{e.text}</span>
                      </li>
                    ))}
                  </ul>
                )}

                <Link
                  href={`/changelog/${r.slug}`}
                  className="mt-4 inline-flex min-h-[44px] items-center gap-1.5 text-sm text-accent hover:underline underline-offset-4"
                >
                  {rest > 0 ? `Read more — ${rest} more change${rest === 1 ? '' : 's'}` : 'Read more'}
                  <ArrowRight size={14} />
                </Link>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
