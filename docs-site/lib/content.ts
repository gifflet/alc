// content.ts — The filesystem IS the navigation.
//
// A page's URL, section and order come from where its file sits on disk, so
// adding a page means adding a file: no registry to update in a second place
// and no chance of a page existing but being unreachable. Everything here runs
// at build time on the server; nothing is shipped to the browser.
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import matter from 'gray-matter'

const CONTENT = join(process.cwd(), 'content')
const DOCS = join(CONTENT, 'docs')

export type Doc = {
  slug: string[]
  href: string
  title: string
  description: string
  order: number
  section: string
  body: string
}

export type Section = { dir: string; label: string; order: number; pages: Doc[] }

function readSectionMeta(dir: string): { label: string; order: number } {
  const metaPath = join(DOCS, dir, '_meta.json')
  if (existsSync(metaPath)) {
    const raw = JSON.parse(readFileSync(metaPath, 'utf8'))
    if (typeof raw.label === 'string') {
      return { label: raw.label, order: Number(raw.order ?? 99) }
    }
  }
  // A section without _meta.json still renders — it just gets a derived label,
  // rather than disappearing from the nav with no error anywhere.
  return { label: dir.replace(/-/g, ' ').replace(/^./, (c) => c.toUpperCase()), order: 99 }
}

function readDoc(dir: string, file: string): Doc {
  const raw = readFileSync(join(DOCS, dir, file), 'utf8')
  const { data, content } = matter(raw)
  const name = file.replace(/\.mdx?$/, '')
  const slug = name === 'index' ? [dir] : [dir, name]
  return {
    slug,
    href: '/docs/' + slug.join('/'),
    title: String(data.title ?? name),
    description: String(data.description ?? ''),
    order: Number(data.order ?? 99),
    section: dir,
    body: content,
  }
}

/** Every section with its pages, both sorted by declared order then title. */
export function getSections(): Section[] {
  if (!existsSync(DOCS)) return []
  return readdirSync(DOCS, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => {
      const meta = readSectionMeta(e.name)
      const pages = readdirSync(join(DOCS, e.name))
        .filter((f) => /\.mdx?$/.test(f))
        .map((f) => readDoc(e.name, f))
        .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title))
      return { dir: e.name, label: meta.label, order: meta.order, pages }
    })
    .filter((s) => s.pages.length > 0)
    .sort((a, b) => a.order - b.order || a.label.localeCompare(b.label))
}

export function getAllDocs(): Doc[] {
  return getSections().flatMap((s) => s.pages)
}

export function getDoc(slug: string[]): Doc | null {
  const target = slug.join('/')
  return getAllDocs().find((d) => d.slug.join('/') === target) ?? null
}

/** Previous/next across the whole tree, so the reader can walk the docs
 *  end to end without returning to the sidebar. */
export function getNeighbours(slug: string[]): { prev: Doc | null; next: Doc | null } {
  const all = getAllDocs()
  const i = all.findIndex((d) => d.slug.join('/') === slug.join('/'))
  if (i === -1) return { prev: null, next: null }
  return { prev: all[i - 1] ?? null, next: all[i + 1] ?? null }
}

export function getLanding(): { title: string; description: string; body: string } {
  const path = join(CONTENT, 'landing.mdx')
  if (!existsSync(path)) return { title: 'ALC', description: '', body: '' }
  const { data, content } = matter(readFileSync(path, 'utf8'))
  return { title: String(data.title ?? 'ALC'), description: String(data.description ?? ''), body: content }
}
