// site.ts — Everything that depends on where the site is deployed.
//
// One constant, because a domain appears in canonicals, the sitemap, robots.txt
// and every Open Graph tag. Scattered across those, a domain change becomes a
// hunt in which the one you miss is the one that quietly points search engines
// at a dead host.
//
// Order matters: an explicit SITE_URL wins, then Vercel's per-deployment host so
// previews describe themselves rather than production, then the production
// default.
function resolveUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_SITE_URL
  if (explicit) return explicit.replace(/\/$/, '')
  const vercel = process.env.NEXT_PUBLIC_VERCEL_URL ?? process.env.VERCEL_URL
  if (vercel) return `https://${vercel.replace(/\/$/, '')}`
  // alc-runtime is the package name on PyPI, so it is the project's canonical
  // identifier rather than an invented one — and "runtime" disambiguates a
  // three-letter acronym that otherwise reads as alcohol. (get-alc.vercel.app
  // is already taken by "GetAlc — Premium Alcohol Discovery Platform".)
  return 'https://alc-runtime.vercel.app'
}

/** Where the site is mounted below the domain root. Empty on Vercel, which
 *  serves at a root. Kept as a seam because a project site (GitHub Pages under
 *  /<repo>) needs every absolute asset path prefixed, and discovering that
 *  after the fact means hunting every <video> and <img> in the tree. */
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? ''

/** Prefix a /public asset with the base path.
 *
 *  Next rewrites hrefs on <Link>, but NOT string src attributes on <video> or
 *  <img>. Under basePath those resolve against the domain root and 404 — the
 *  hero demo silently stopped loading the first time this was exported. */
export function asset(path: string): string {
  return `${BASE_PATH}${path.startsWith('/') ? path : `/${path}`}`
}

export const SITE = {
  url: resolveUrl(),
  name: 'ALC',
  title: 'ALC — Agentic Layer Compiler & Runtime',
  tagline: 'A control plane for agentic coding',
  description:
    'ALC runs coding agents behind deterministic verification. Declare how your agents should work once, run it on any engine, and nothing is reported done until your own checks pass.',
  repo: 'https://github.com/gifflet/alc',
  pypi: 'https://pypi.org/project/alc-runtime/',
  locale: 'en_US',
} as const

/** Absolute URL for a site-relative path.
 *
 *  Deliberately string concatenation, not `new URL(path, base)`. A path that
 *  starts with "/" is host-absolute, so `new URL('/docs/x', 'https://h/alc')`
 *  resolves to `https://h/docs/x` — silently dropping the base path. That put
 *  every sitemap entry on a URL that does not exist. */
export function absolute(path: string): string {
  const base = SITE.url.replace(/\/$/, '')
  const rel = path.startsWith('/') ? path : `/${path}`
  return rel === '/' ? base : `${base}${rel}`
}
