import { fileURLToPath } from 'node:url'

/** @type {import('next').NextConfig} */
export default {
  // Without this, Turbopack walks up looking for a lockfile, finds one in the
  // home directory outside the repo, and roots the build there.
  turbopack: { root: fileURLToPath(new URL('.', import.meta.url)) },
  // Content is read from content/ at build time; nothing is per-request, so
  // every route prerenders.
  // The install routes read their script from scripts-dist/ at build time, so
  // tracing has to carry those files into the deployment.
  outputFileTracingIncludes: {
    '/docs/**': ['./content/**/*'],
    '/install.sh': ['./scripts-dist/install.sh'],
    '/install.ps1': ['./scripts-dist/install.ps1'],
  },
}
