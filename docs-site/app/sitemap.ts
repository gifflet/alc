import type { MetadataRoute } from 'next'
import { statSync } from 'node:fs'
import { join } from 'node:path'
import { getAllDocs, getSections } from '@/lib/content'
import { getReleases } from '@/lib/changelog'
import { SITE, absolute } from '@/lib/site'

/** The file's own mtime. Honest by construction: it moves when the page is
 *  actually edited, which is the only thing lastModified is supposed to mean.
 *  A build timestamp would tell crawlers every page changed on every deploy,
 *  and they learn to ignore a signal that is always "just now". */
function editedAt(section: string, slug: string[]): Date | undefined {
  const file = slug.length === 1 ? 'index.mdx' : `${slug[slug.length - 1]}.mdx`
  try {
    return statSync(join(process.cwd(), 'content/docs', section, file)).mtime
  } catch {
    return undefined
  }
}

// Under `output: export` a route handler must declare itself static, or the
// build refuses to guess whether it can be emitted as a file.
export const dynamic = 'force-static'

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const firstOfSection = new Set(getSections().map((s) => s.pages[0]?.href))

  const releases = await getReleases()

  return [
    {
      url: SITE.url,
      lastModified: (() => {
        try {
          return statSync(join(process.cwd(), 'content/landing.mdx')).mtime
        } catch {
          return undefined
        }
      })(),
      changeFrequency: 'monthly',
      priority: 1,
    },
    ...getAllDocs().map((doc) => ({
      url: absolute(doc.href),
      lastModified: editedAt(doc.section, doc.slug),
      changeFrequency: 'monthly' as const,
      // A section's opening page is the one worth surfacing first; the rest are
      // equal to each other. Priority is a hint about relative importance
      // within this site, nothing more — inflating everything to 1.0 says the
      // same as saying nothing.
      priority: firstOfSection.has(doc.href) ? 0.8 : 0.6,
    })),
    // The changelog index changes on every release; the per-version pages never
    // change once cut, and say so.
    { url: absolute('/changelog'), lastModified: releases[0]?.date, changeFrequency: 'weekly' as const, priority: 0.7 },
    ...releases.map((r) => ({
      url: absolute(`/changelog/${r.slug}`),
      lastModified: r.date,
      changeFrequency: 'yearly' as const,
      priority: 0.4,
    })),
  ]
}
