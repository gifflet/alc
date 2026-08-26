# alc-docs

The documentation site for ALC — landing page plus the `/docs` tree.

```bash
npm install
npm run dev     # http://localhost:3000
npm run build   # production build
npm run lint    # tsc --noEmit
```

## How content works

Pages are MDX files under `content/`. The filesystem is the navigation: a file's
path decides its URL, its section and its position, so adding a page means adding
a file — there is no separate registry that can drift out of sync.

```
content/
  landing.mdx                     → /
  docs/<section>/_meta.json       → the section's label and order in the sidebar
  docs/<section>/<page>.mdx       → /docs/<section>/<page>
```

Every page carries frontmatter:

```yaml
---
title: Quick start
description: One sentence, under 160 characters.
order: 1
---
```

`order` sorts pages inside a section; `_meta.json` sorts the sections themselves.
Both fall back to a sane default when absent, so a missing field degrades the
ordering rather than breaking the build.

## Stack

Next.js (App Router) · MDX · Shiki for build-time highlighting · Radix for the
mobile navigation sheet · Tailwind v4. The palette is lifted verbatim from
`ui/src/index.css` so the site and the app read as one instrument.
