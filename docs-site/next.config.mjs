import { fileURLToPath } from 'node:url'

/** @type {import('next').NextConfig} */
export default {
  // Without this, Turbopack walks up looking for a lockfile, finds one in the
  // home directory outside the repo, and roots the build there.
  turbopack: { root: fileURLToPath(new URL('.', import.meta.url)) },
  // Content is read from content/ at build time; nothing is per-request, so
  // every route prerenders.
  outputFileTracingIncludes: { '/docs/**': ['./content/**/*'] },
}
