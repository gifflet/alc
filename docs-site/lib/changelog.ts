// changelog.ts — Builds the changelog from what the project already produces.
//
// No hand-written CHANGELOG.md. A second file describing the same history has
// to be remembered on every release, and the one that drifts is always the one
// people read. The sources here are byproducts of shipping:
//
//   - GitHub Releases give the version and the date.
//   - The commits in each release give the entries, already categorised,
//     because they follow Conventional Commits.
//   - The `chore(release): X.Y.Z — <headline>` commit carries the editorial
//     summary that was written when the release was cut.
//
// Fetched at build time. If GitHub is unreachable the page degrades to a link
// rather than failing the build — a docs site should not stop deploying because
// an API was slow.

const REPO = 'gifflet/alc'
const API = `https://api.github.com/repos/${REPO}`

export type Entry = { kind: 'feat' | 'fix' | 'perf' | 'other'; scope?: string; text: string }
export type Release = {
  version: string
  slug: string
  date: string
  headline: string | null
  features: Entry[]
  fixes: Entry[]
  other: Entry[]
}

/** 0.41.1 → 0-41-1, so a version reads as one path segment. */
export function toSlug(version: string): string {
  return version.replace(/^v/, '').replace(/\./g, '-')
}

async function gh<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API}${path}`, {
      headers: {
        accept: 'application/vnd.github+json',
        ...(process.env.GITHUB_TOKEN ? { authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}),
      },
      // Revalidate rather than cache forever: a redeploy days later should pick
      // up releases cut in between.
      next: { revalidate: 3600 },
    })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

const CONVENTIONAL = /^(feat|fix|perf|refactor|docs|chore|build|ci|test|style)(\(([^)]+)\))?!?:\s*(.+)$/

/** The release commit's subject doubles as the headline for the version:
 *  `chore(release): 0.41.0 — engine auto-detection and …`. */
function headlineFrom(subject: string): string | null {
  const m = /^chore\(release\):\s*\d+\.\d+\.\d+\s*[—–-]\s*(.+)$/.exec(subject)
  if (!m) return null
  return m[1].charAt(0).toUpperCase() + m[1].slice(1)
}

function classify(subject: string): Entry | null {
  const m = CONVENTIONAL.exec(subject)
  if (!m) return null
  const [, type, , scope, rest] = m
  // The release commit is the headline, not an entry — listing it would repeat
  // the page's own title back at the reader.
  if (type === 'chore' && scope === 'release') return null
  const kind: Entry['kind'] =
    type === 'feat' ? 'feat' : type === 'fix' ? 'fix' : type === 'perf' ? 'perf' : 'other'
  return { kind, scope, text: rest.charAt(0).toUpperCase() + rest.slice(1) }
}

export async function getReleases(): Promise<Release[]> {
  const tags = await gh<{ tag_name: string; published_at: string }[]>('/releases?per_page=30')
  if (!tags || tags.length === 0) return []

  const out: Release[] = []
  for (let i = 0; i < tags.length; i++) {
    const tag = tags[i]
    const previous = tags[i + 1]
    let subjects: string[] = []

    if (previous) {
      const cmp = await gh<{ commits: { commit: { message: string } }[] }>(
        `/compare/${previous.tag_name}...${tag.tag_name}`,
      )
      subjects = (cmp?.commits ?? []).map((c) => c.commit.message.split('\n')[0])
    }

    const headline = subjects.map(headlineFrom).find(Boolean) ?? null
    const entries = subjects.map(classify).filter((e): e is Entry => e !== null)

    out.push({
      version: tag.tag_name.replace(/^v/, ''),
      slug: toSlug(tag.tag_name),
      date: tag.published_at,
      headline,
      features: entries.filter((e) => e.kind === 'feat'),
      fixes: entries.filter((e) => e.kind === 'fix' || e.kind === 'perf'),
      other: entries.filter((e) => e.kind === 'other'),
    })
  }
  return out
}

export async function getRelease(slug: string): Promise<Release | null> {
  return (await getReleases()).find((r) => r.slug === slug) ?? null
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  })
}
