import { getSections } from '@/lib/content'
import { Sidebar } from '@/components/Sidebar'

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  const sections = getSections().map((s) => ({
    label: s.label,
    pages: s.pages.map((p) => ({ href: p.href, title: p.title })),
  }))

  return (
    <div className="mx-auto max-w-[1200px] px-4">
      <div className="flex gap-10">
        {/* Sticky rather than fixed: it scrolls with the page until it reaches
            the header, which keeps it out of the way on a short viewport. */}
        <aside className="hidden lg:block w-56 shrink-0">
          <div className="sticky top-14 max-h-[calc(100vh-3.5rem)] overflow-y-auto py-8 pr-2">
            <Sidebar sections={sections} />
          </div>
        </aside>
        <main id="content" className="min-w-0 flex-1">
          {children}
        </main>
      </div>
    </div>
  )
}
