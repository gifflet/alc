// landing.ts — Parses content/landing.mdx into the shape the page renders.
//
// The copy stays in one MDX file so it reads as prose and can be edited without
// touching JSX. The format is deliberately dumb — `## Section: Name`, then
// `### Field`, then the value — because a landing page is a fixed set of slots,
// not a document tree. Anything richer would be a parser to maintain.
import { getLanding } from './content'

export type Fields = Record<string, string>
export type Cta = { label: string; href: string }

function parse(body: string): Record<string, Fields> {
  const sections: Record<string, Fields> = {}
  let section: string | null = null
  let field: string | null = null
  let buffer: string[] = []

  const flush = () => {
    if (section && field) {
      sections[section][field] = buffer.join('\n').trim()
    }
    buffer = []
  }

  for (const line of body.split('\n')) {
    const sec = /^##\s+Section:\s*(.+)$/.exec(line)
    if (sec) {
      flush()
      section = sec[1].trim()
      field = null
      sections[section] ??= {}
      continue
    }
    const fld = /^###\s+(.+)$/.exec(line)
    if (fld) {
      flush()
      field = fld[1].trim()
      continue
    }
    if (line.trim() === '---') continue // section divider
    if (section && field) buffer.push(line)
  }
  flush()
  return sections
}

/** "Label: X\nLink: /y" → a link. Returns null when either half is missing, so
 *  a half-written CTA renders as nothing rather than as a dead button. */
function cta(raw: string | undefined): Cta | null {
  if (!raw) return null
  const label = /^Label:\s*(.+)$/m.exec(raw)?.[1]?.trim()
  const href = /^Link:\s*(.+)$/m.exec(raw)?.[1]?.trim()
  return label && href ? { label, href } : null
}

/** "Title: X\nBody: Y" → an item. Body may wrap across lines. */
function item(raw: string | undefined): { title: string; body: string } | null {
  if (!raw) return null
  const title = /^Title:\s*(.+)$/m.exec(raw)?.[1]?.trim()
  const body = /^Body:\s*([\s\S]+)$/m.exec(raw)?.[1]?.trim()
  return title && body ? { title, body } : null
}

/** Collects `Step 1`, `Step 2`… in order, stopping at the first gap. */
function series(fields: Fields, prefix: string) {
  const out: { title: string; body: string }[] = []
  for (let i = 1; ; i++) {
    const parsed = item(fields[`${prefix} ${i}`])
    if (!parsed) break
    out.push(parsed)
  }
  return out
}

/** Strips the fence so the code can be rendered by our own terminal component
 *  rather than going through the MDX pipeline for four lines. */
function code(raw: string | undefined): string[] {
  if (!raw) return []
  return raw
    .replace(/^```\w*\n?/, '')
    .replace(/```$/, '')
    .split('\n')
    .map((l) => l.trimEnd())
}

export function getLandingContent() {
  const { title, description, body } = getLanding()
  const s = parse(body)
  const hero = s['Hero'] ?? {}
  const problem = s['Problem'] ?? {}
  const how = s['How it works'] ?? {}
  const features = s['Features'] ?? {}
  const ladder = s['Ladder'] ?? {}
  const start = s['Get started'] ?? {}

  return {
    title,
    description,
    hero: {
      eyebrow: hero['Eyebrow'] ?? '',
      headline: hero['Headline'] ?? '',
      subheadline: hero['Subheadline'] ?? '',
      primary: cta(hero['Primary CTA']),
      secondary: cta(hero['Secondary CTA']),
      code: code(hero['Hero code block']),
      caption: hero['Hero caption'] ?? '',
    },
    problem: {
      heading: problem['Section heading'] ?? '',
      body: (problem['Body'] ?? '').split('\n\n').filter(Boolean),
      quote: problem['Pull quote'] ?? '',
      // Real output, as selectable text. The demo video already shows a run;
      // what the page had nowhere was a transcript you can read on a phone,
      // search, or copy — which for a CLI is the demo.
      transcript: code(problem['Transcript']),
    },
    how: {
      heading: how['Section heading'] ?? '',
      body: (how['Body'] ?? '').split('\n\n').filter(Boolean),
      steps: series(how, 'Step'),
      caption: how['Diagram caption'] ?? '',
    },
    features: {
      heading: features['Section heading'] ?? '',
      items: series(features, 'Feature'),
    },
    ladder: {
      heading: ladder['Section heading'] ?? '',
      body: ladder['Body'] ?? '',
      rungs: series(ladder, 'Rung'),
      closing: ladder['Closing line'] ?? '',
    },
    start: {
      heading: start['Section heading'] ?? '',
      // Split like `problem.body` and `how.body`: this field was a single string,
      // so a second paragraph written here rendered glued to the first inside one
      // <p>. Silent, and only visible on the page.
      body: (start['Body'] ?? '').split('\n\n').filter(Boolean),
      code: code(start['Code block']),
      primary: cta(start['Primary CTA']),
      secondary: cta(start['Secondary CTA']),
      note: start['Footer note'] ?? '',
    },
  }
}
