import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import { getAllDocs, getDoc, getNeighbours, getSections } from '@/lib/content'
import { renderMdx, extractHeadings } from '@/lib/mdx'
import { SITE, absolute } from '@/lib/site'
import { TableOfContents } from '@/components/TableOfContents'

type Params = { slug?: string[] }

/** Every page is known at build time, so the whole tree prerenders. */
export function generateStaticParams(): Params[] {
  return [{ slug: [] }, ...getAllDocs().map((d) => ({ slug: d.slug }))]
}

function firstDocHref(): string {
  return getSections()[0]?.pages[0]?.href ?? '/'
}

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>
}): Promise<Metadata> {
  const { slug } = await params
  if (!slug || slug.length === 0) {
    // /docs forwards to the first page and has no content of its own, so it
    // should not compete with that page in an index.
    return { title: 'Documentation', robots: { index: false, follow: true } }
  }
  const doc = getDoc(slug)
  if (!doc) return {}
  return {
    title: doc.title,
    description: doc.description,
    // Self-referencing canonical: the page is reachable at exactly one URL and
    // says so, which settles any question a crawler might have about
    // trailing slashes or query strings.
    alternates: { canonical: doc.href },
    openGraph: {
      type: 'article',
      url: absolute(doc.href),
      title: doc.title,
      description: doc.description,
      siteName: SITE.name,
    },
    twitter: { card: 'summary_large_image', title: doc.title, description: doc.description },
  }
}

export default async function DocPage({ params }: { params: Promise<Params> }) {
  const { slug } = await params

  // /docs itself has no content of its own — it forwards to the first page
  // rather than rendering an index that would duplicate the sidebar.
  if (!slug || slug.length === 0) {
    return (
      <div className="py-16">
        <p className="text-muted">
          <Link href={firstDocHref()} className="text-accent underline underline-offset-4">
            Start with the installation guide
          </Link>
        </p>
      </div>
    )
  }

  const doc = getDoc(slug)
  if (!doc) notFound()

  const content = await renderMdx(doc.body)
  const headings = extractHeadings(doc.body)
  const { prev, next } = getNeighbours(slug)

  return (
    <div className="flex gap-10">
      <article className="min-w-0 flex-1 py-8">
        <header className="mb-8">
          <h1 className="text-3xl font-semibold tracking-tight">{doc.title}</h1>
          {doc.description && <p className="mt-2.5 text-muted leading-relaxed">{doc.description}</p>}
        </header>

        <div className="prose">{content}</div>

        <nav aria-label="Adjacent pages" className="mt-16 flex flex-wrap gap-3 border-t border-border pt-6 text-sm">
          {prev && (
            <Link
              href={prev.href}
              className="group flex min-h-[44px] flex-1 items-center gap-2.5 rounded-md border border-border px-4 py-2 transition-colors hover:border-faint"
            >
              <ArrowLeft size={15} className="shrink-0 text-faint group-hover:text-accent" />
              <span className="min-w-0">
                <span className="block text-[11px] uppercase tracking-wider text-faint">Previous</span>
                <span className="block truncate text-primary">{prev.title}</span>
              </span>
            </Link>
          )}
          {next && (
            <Link
              href={next.href}
              className="group flex min-h-[44px] flex-1 items-center justify-end gap-2.5 rounded-md border border-border px-4 py-2 text-right transition-colors hover:border-faint"
            >
              <span className="min-w-0">
                <span className="block text-[11px] uppercase tracking-wider text-faint">Next</span>
                <span className="block truncate text-primary">{next.title}</span>
              </span>
              <ArrowRight size={15} className="shrink-0 text-faint group-hover:text-accent" />
            </Link>
          )}
        </nav>
      </article>

      <aside className="hidden xl:block w-52 shrink-0">
        <div className="sticky top-14 max-h-[calc(100vh-3.5rem)] overflow-y-auto py-8">
          <TableOfContents headings={headings} />
        </div>
      </aside>
    </div>
  )
}
