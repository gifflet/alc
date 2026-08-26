import type { Metadata } from 'next'
import './globals.css'
import { SITE, asset, absolute } from '@/lib/site'
import { SiteJsonLd } from '@/components/SiteJsonLd'
import { SiteHeader } from '@/components/SiteHeader'
import { SiteFooter } from '@/components/SiteFooter'

export const metadata: Metadata = {
  metadataBase: new URL(SITE.url),
  title: { default: SITE.title, template: `%s · ${SITE.name}` },
  description: SITE.description,
  applicationName: SITE.name,
  // Written for a search result, not for a slide: what it is, what it does.
  keywords: [
    'agentic coding',
    'coding agent',
    'control plane',
    'Claude Code',
    'Gemini CLI',
    'CI for AI agents',
    'agent orchestration',
    'developer tools',
  ],
  authors: [{ name: 'gifflet', url: SITE.repo }],
  creator: 'gifflet',
  // Canonical on the root; each docs page overrides with its own.
  alternates: { canonical: '/' },
  openGraph: {
    type: 'website',
    url: SITE.url,
    siteName: SITE.name,
    title: SITE.title,
    description: SITE.description,
    locale: SITE.locale,
    images: [{ url: absolute('/og.png'), width: 1200, height: 630, alt: `${SITE.name} — ${SITE.tagline}` }],
  },
  twitter: {
    card: 'summary_large_image',
    title: SITE.title,
    description: SITE.description,
    images: [absolute('/og.png')],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, 'max-image-preview': 'large', 'max-snippet': -1 },
  },
  // Search Console ownership. Next renders this as
  // <meta name="google-site-verification" content="…"> in the head.
  //
  // Not a secret — it is served publicly in the HTML by design, which is how
  // Google reads it. It must stay after verification succeeds: removing it
  // eventually drops ownership of the property.
  verification: { google: '1BYSLnSisrHVUhECfHa1fbzW2Qo9zHBLdNMhyTnHM6M' },
  icons: {
    icon: [{ url: asset('/brand/favicon.svg'), type: 'image/svg+xml' }],
    apple: asset('/brand/apple-touch-icon.png'),
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased min-h-screen flex flex-col">
        <SiteJsonLd />
        <a
          href="#content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:inline-flex focus:min-h-[44px] focus:items-center focus:rounded-md focus:bg-panel focus:px-4 focus:text-sm focus:text-primary focus:shadow-[var(--elev-2)]"
        >
          Skip to content
        </a>
        <SiteHeader />
        <div className="flex-1">{children}</div>
        <SiteFooter />
      </body>
    </html>
  )
}
