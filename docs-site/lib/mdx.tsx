// mdx.tsx — One MDX pipeline, used by both the docs pages and the landing.
//
// Highlighting happens at build time via Shiki, so no highlighter ships to the
// browser and code is readable before hydration (or without JS at all). Both
// themes are emitted as CSS variables and the stylesheet picks one, which keeps
// the light/dark switch free of a second render.
import { compileMDX } from 'next-mdx-remote/rsc'
import { Install } from '@/components/landing/Install'
import rehypePrettyCode from 'rehype-pretty-code'
import rehypeSlug from 'rehype-slug'
import rehypeAutolinkHeadings from 'rehype-autolink-headings'
import remarkGfm from 'remark-gfm'
import type { Options as PrettyCodeOptions } from 'rehype-pretty-code'

const prettyCode: PrettyCodeOptions = {
  theme: { dark: 'github-dark-dimmed', light: 'github-light' },
  keepBackground: false,
  defaultLang: 'text',
}

export async function renderMdx(source: string) {
  const { content } = await compileMDX({
    source,
    // The only components MDX may reach for. Kept to a short, deliberate list:
    // a docs page that can render anything is a docs page nobody can review.
    components: { Install },
    options: {
      mdxOptions: {
        remarkPlugins: [remarkGfm],
        rehypePlugins: [
          rehypeSlug,
          [rehypePrettyCode, prettyCode],
          [
            rehypeAutolinkHeadings,
            {
              behavior: 'append',
              properties: { className: 'heading-anchor', ariaHidden: true, tabIndex: -1 },
              content: { type: 'text', value: '#' },
            },
          ],
        ],
      },
    },
  })
  return content
}

/** Headings for the on-page table of contents. Parsed from the raw MDX rather
 *  than the rendered tree — the slugs match what rehype-slug generates. */
export function extractHeadings(source: string): { id: string; text: string; depth: 2 | 3 }[] {
  const out: { id: string; text: string; depth: 2 | 3 }[] = []
  // Fenced code can contain lines starting with ##; strip fences first so a
  // comment inside a bash block never becomes a table-of-contents entry.
  const withoutCode = source.replace(/```[\s\S]*?```/g, '')
  for (const line of withoutCode.split('\n')) {
    const m = /^(#{2,3})\s+(.+?)\s*$/.exec(line)
    if (!m) continue
    const text = m[2].replace(/`/g, '').trim()
    const id = text
      .toLowerCase()
      .replace(/[^\w\s-]/g, '')
      .trim()
      .replace(/\s+/g, '-')
    out.push({ id, text, depth: m[1].length as 2 | 3 })
  }
  return out
}
