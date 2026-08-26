import { SITE, absolute } from '@/lib/site'

// SiteJsonLd — structured data, limited to what is verifiably true.
//
// Every field here can be checked against the repository or PyPI. Deliberately
// absent: Organization (there is no organisation), aggregateRating and
// reviewCount (no reviews exist), and any author entity beyond the actual
// GitHub account. Inventing those is the fastest way to earn a manual action,
// and it would make the page claim something the project cannot back.
export function SiteJsonLd() {
  const graph = [
    {
      '@type': 'WebSite',
      '@id': absolute('/#website'),
      url: SITE.url,
      name: SITE.name,
      description: SITE.description,
      inLanguage: 'en',
    },
    {
      '@type': 'SoftwareApplication',
      '@id': absolute('/#software'),
      name: SITE.name,
      alternateName: 'Agentic Layer Compiler & Runtime',
      description: SITE.description,
      applicationCategory: 'DeveloperApplication',
      operatingSystem: 'macOS, Linux, Windows',
      url: SITE.url,
      downloadUrl: SITE.pypi,
      codeRepository: SITE.repo,
      programmingLanguage: 'Python',
      license: 'https://opensource.org/licenses/MIT',
      // It is genuinely free and open source; this is not a pricing claim.
      offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
      author: { '@type': 'Person', name: 'gifflet', url: SITE.repo },
    },
  ]

  return (
    <script
      type="application/ld+json"
      // The payload is built from constants in this file — no user input reaches it.
      dangerouslySetInnerHTML={{ __html: JSON.stringify({ '@context': 'https://schema.org', '@graph': graph }) }}
    />
  )
}
