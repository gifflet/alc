import type { MetadataRoute } from 'next'
import { SITE, absolute } from '@/lib/site'

// Under `output: export` a route handler must declare itself static, or the
// build refuses to guess whether it can be emitted as a file.
export const dynamic = 'force-static'

export default function robots(): MetadataRoute.Robots {
  return {
    // Everything here is public documentation meant to be found. There is no
    // private area to exclude, so a blanket allow is the honest rule — a
    // disallow list that names nothing real only invites misreading.
    rules: [{ userAgent: '*', allow: '/' }],
    sitemap: absolute('/sitemap.xml'),
    host: SITE.url,
  }
}
