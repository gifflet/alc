// check-content.mjs — Guards the docs against the two failures that a build
// cannot catch: a page that is unreachable, and a page that documents a command
// the CLI does not have.
//
// The second one matters more than it looks. Documentation that invents a flag
// is worse than missing documentation: the reader trusts it, runs it, and gets
// an argparse error with no idea whether they or the docs are wrong.
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = new URL('..', import.meta.url).pathname
const DOCS = join(ROOT, 'content/docs')
const CLI = join(ROOT, '../src/alc/cli.py')

const problems = []
const fail = (file, msg) => problems.push(`${relative(ROOT, file)}: ${msg}`)

/** Frontmatter, parsed just enough — a full YAML parser is not needed for three
 *  scalar fields, and this keeps the check dependency-free. */
function frontmatter(raw) {
  const m = /^---\n([\s\S]*?)\n---/.exec(raw)
  if (!m) return null
  const out = {}
  for (const line of m[1].split('\n')) {
    const kv = /^([a-z]+):\s*(.*)$/.exec(line)
    if (kv) out[kv[1]] = kv[2].replace(/^["']|["']$/g, '')
  }
  return out
}

/** Body with fenced blocks removed. Every content rule below cares about prose
 *  only: a `# .alc/manifest.yaml` comment inside a YAML block is not a heading,
 *  and `alc <subcommand>` inside a usage line is not an invocation. Checking the
 *  raw text flags both and trains the reader to ignore the checker. */
function prose(body) {
  const out = []
  let inFence = false
  for (const line of body.split('\n')) {
    if (line.startsWith('```')) { inFence = !inFence; continue }
    if (!inFence) out.push(line)
  }
  return out.join('\n')
}

const files = []
for (const dir of readdirSync(DOCS, { withFileTypes: true }).filter((e) => e.isDirectory())) {
  const sectionDir = join(DOCS, dir.name)
  if (!existsSync(join(sectionDir, '_meta.json'))) {
    fail(sectionDir, 'section has no _meta.json, so its sidebar label and order are guessed')
  }
  for (const f of readdirSync(sectionDir).filter((f) => f.endsWith('.mdx'))) {
    files.push(join(sectionDir, f))
  }
}

if (files.length === 0) problems.push('content/docs contains no pages')

for (const file of files) {
  const raw = readFileSync(file, 'utf8')
  const fm = frontmatter(raw)
  if (!fm) {
    fail(file, 'missing frontmatter block')
    continue
  }
  for (const key of ['title', 'description', 'order']) {
    if (!fm[key]) fail(file, `frontmatter is missing "${key}"`)
  }
  if (fm.description && fm.description.length > 200) {
    fail(file, `description is ${fm.description.length} chars; keep it under 200 for meta tags`)
  }
  // The page template renders the frontmatter title as the <h1>. A second one in
  // the body would give the page two competing document titles.
  const body = raw.slice(raw.indexOf('---', 3) + 3)
  if (/^#\s+/m.test(prose(body))) fail(file, 'body contains an <h1>; the frontmatter title already is one')
  // A fenced block with no language gets no highlighting. Only OPENING fences
  // carry one — the closing ``` never does, so track which is which instead of
  // matching every fence line and flagging half of them.
  let inFence = false
  for (const line of body.split('\n')) {
    if (!line.startsWith('```')) continue
    if (inFence) { inFence = false; continue }
    inFence = true
    if (line.trim() === '```') fail(file, 'fenced code block without a language')
  }
}

// Every `alc <sub>` mentioned anywhere must exist in the CLI.
if (existsSync(CLI)) {
  const cli = readFileSync(CLI, 'utf8')
  const real = new Set([...cli.matchAll(/\.add_parser\(\s*\n?\s*"([a-z][a-z_-]*)"/g)].map((m) => m[1]))
  for (const file of files) {
    const body = readFileSync(file, 'utf8')
    for (const m of body.matchAll(/\balc\s+([a-z][a-z-]+)/g)) {
      // "the alc command" and similar prose is not an invocation.
      // Prose mentions and syntax placeholders are not invocations.
      if (['command', 'commands', 'subcommand', 'runtime'].includes(m[1])) continue
      if (!real.has(m[1])) fail(file, `documents "alc ${m[1]}", which is not a subcommand in cli.py`)
    }
  }
} else {
  console.warn('note: cli.py not found, skipped the command cross-check')
}

// Internal links, checked against the routes that actually exist. A broken link
// in the nav is invisible to the build: Next renders the anchor happily and the
// reader gets a 404. This caught /docs/getting-started/install (the page is
// "installation") in the header of the very first build.
const routes = new Set(files.map((f) => '/docs/' + relative(DOCS, f).replace(/\.mdx$/, '')))
const linkSources = [
  ...files,
  ...['components/SiteHeader.tsx', 'components/SiteFooter.tsx', 'app/page.tsx', 'app/not-found.tsx']
    .map((f) => join(ROOT, f))
    .filter((f) => existsSync(f)),
  join(ROOT, 'content/landing.mdx'),
].filter((f) => existsSync(f))

for (const file of linkSources) {
  const raw = readFileSync(file, 'utf8')
  const hrefs = [
    ...[...raw.matchAll(/href="(\/docs\/[^"#]*)"/g)].map((m) => m[1]),
    ...[...raw.matchAll(/\]\((\/docs\/[^)#]*)\)/g)].map((m) => m[1]),
    ...[...raw.matchAll(/^Link:\s*(\/docs\/\S+)$/gm)].map((m) => m[1]),
  ]
  for (const href of hrefs) {
    const clean = href.replace(/\/$/, '')
    if (clean === '/docs') continue
    if (!routes.has(clean)) fail(file, `links to ${clean}, which is not a page`)
  }
}

if (problems.length > 0) {
  console.error(`content check failed (${problems.length}):\n` + problems.map((p) => `  ${p}`).join('\n'))
  process.exit(1)
}
console.log(`content check passed — ${files.length} pages`)
