import Link from 'next/link'
import {
  ArrowRight,
  Boxes,
  Cpu,
  Gauge,
  GitBranch,
  Layers,
  ShieldCheck,
  Target,
  Timer,
} from 'lucide-react'
import { getLandingContent } from '@/lib/landing'
import { inline } from '@/lib/inline'
import { asset } from '@/lib/site'
import { Card, Eyebrow, Lede, Section, SectionTitle, Terminal, WideRow } from '@/components/landing/primitives'
import { Demo } from '@/components/landing/Demo'
import { Install } from '@/components/landing/Install'
import type { Cta } from '@/lib/landing'

/** Primary is white-on-dark rather than the accent blue. The blue is a status
 *  colour everywhere else in the product — it means "link" or "running" — and
 *  spending it on a marketing button weakens what it means on the next screen. */
function CtaLink({ cta, variant }: { cta: Cta; variant: 'primary' | 'secondary' }) {
  const base =
    'inline-flex min-h-[46px] items-center gap-2 rounded-md px-5 text-[15px] font-medium transition-all duration-150'
  const style =
    variant === 'primary'
      ? 'bg-primary text-base hover:opacity-90'
      : 'border border-border text-primary hover:border-faint hover:bg-hover'
  return (
    <Link href={cta.href} className={`${base} ${style}`}>
      {cta.label}
      {variant === 'primary' && <ArrowRight size={16} />}
    </Link>
  )
}

const FEATURE_ICONS = [ShieldCheck, Cpu, Target, Layers, Timer, GitBranch, Boxes, Gauge]

export default function Home() {
  const c = getLandingContent()

  return (
    <main id="content">
      {/* ---------------------------------------------------------------- Hero
          Centred, not split. The two-column version made the copy and the demo
          compete for the same moment; stacking them gives an order — read this,
          then watch that — and lets the demo be three times larger. */}
      <section className="hero-ground hero-grid relative overflow-hidden">
        <div className="relative mx-auto max-w-[1200px] px-4 pt-16 pb-0 text-center md:pt-20">
          <p className="inline-flex items-center gap-2 rounded-full border border-border bg-panel/70 px-3.5 py-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-faint">
            {c.hero.eyebrow}
          </p>

          <h1 className="mx-auto mt-6 max-w-[19ch] text-[2.75rem] font-semibold leading-[1.05] tracking-[-0.028em] text-balance sm:text-6xl lg:text-[4.25rem]">
            {c.hero.headline}
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-muted text-pretty sm:text-xl">
            {inline(c.hero.subheadline)}
          </p>

          {/* The install command IS the primary call to action for a CLI. It sits
              above the links, which drop to secondary — reading the docs is what
              you do after the tool is on your machine, not instead. */}
          <div className="mt-9 px-1">
            <Install />
          </div>

          <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
            {c.hero.primary && <CtaLink cta={c.hero.primary} variant="primary" />}
            {c.hero.secondary && <CtaLink cta={c.hero.secondary} variant="secondary" />}
          </div>

          {c.hero.caption && (
            <p className="mx-auto mt-5 hidden max-w-xl text-sm leading-relaxed text-faint sm:block">
              {inline(c.hero.caption)}
            </p>
          )}
        </div>

        {/* The demo starts inside the hero's dark ground and continues past the
            fold, so the page invites a scroll instead of ending at the button. */}
        <div className="relative mt-11 px-4 pb-16 md:mt-12 md:pb-24">
          <WideRow>
            {/* The recording is a 92-column terminal. Scaled into 370px of phone
                it is unreadable, and an unreadable demo informs nobody — so a
                narrow screen gets the commands as text that wraps instead. */}
            <div className="sm:hidden">
              <Terminal
                lines={c.hero.code.filter(Boolean).map((line) => {
                  const [cmd, note] = line.split(/\s{2,}#\s*/)
                  return { cmd: cmd.trim(), note: note?.trim() }
                })}
              />
              <p className="mt-3.5 text-left text-sm leading-relaxed text-faint">
                {inline(c.hero.caption)}
              </p>
            </div>
            <div className="hidden sm:block">
              <Demo
                src={asset("/demo/alc-run.mp4")}
                poster={asset("/demo/alc-run.jpg")}
                width={1480}
                height={660}
                label="A recorded alc run: Act, Verify, and the checks passing"
                caption="A real run, not a mock-up — the timings, the cost and the Scorecard are what the tool printed."
              />
            </div>
          </WideRow>
        </div>
      </section>

      {/* ------------------------------------------------------------- Problem */}
      <Section className="reveal border-t border-border">
        <div className="mx-auto max-w-3xl text-center">
          <SectionTitle>{c.problem.heading}</SectionTitle>
        </div>
        <div className="mx-auto mt-9 grid max-w-5xl gap-8 md:grid-cols-[1.35fr_1fr] md:items-start">
          <div className="space-y-4">
            {c.problem.body.map((p) => (
              <p key={p.slice(0, 24)} className="text-[17px] leading-relaxed text-muted text-pretty">
                {inline(p)}
              </p>
            ))}
          </div>
          {c.problem.quote && (
            <blockquote className="rounded-lg border-l-2 border-accent bg-panel px-6 py-5 text-xl font-medium leading-snug text-primary text-balance">
              {c.problem.quote}
            </blockquote>
          )}
        </div>
      </Section>

      {/* -------------------------------------------------------- How it works */}
      <Section className="reveal border-t border-border">
        <div className="mx-auto max-w-3xl text-center">
          <SectionTitle>{c.how.heading}</SectionTitle>
          {c.how.body.map((p) => (
            <p key={p.slice(0, 24)} className="mx-auto mt-4 text-[17px] leading-relaxed text-muted text-pretty">
              {inline(p)}
            </p>
          ))}
        </div>
        <ol className="mt-12 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {c.how.steps.map((step, i) => (
            <li key={step.title} className="rounded-lg border border-border bg-panel p-6">
              <span className="font-mono text-xs text-accent">{String(i + 1).padStart(2, '0')}</span>
              <h3 className="mt-2.5 text-[17px] font-medium text-primary">{step.title}</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-muted">{inline(step.body)}</p>
            </li>
          ))}
        </ol>
        {c.how.caption && (
          <p className="mt-6 text-center font-mono text-xs text-faint">{c.how.caption}</p>
        )}
      </Section>

      {/* ---------------------------------------------------------- The web UI
          Its own full-width moment. The UI is the half of the product a
          screenshot can actually sell, so it gets the room the hero gets. */}
      <Section className="reveal border-t border-border">
        <div className="mx-auto max-w-3xl text-center">
          <Eyebrow>alc ui</Eyebrow>
          <SectionTitle>Watch the loop instead of tailing a log</SectionTitle>
          <p className="mx-auto mt-4 text-[17px] leading-relaxed text-muted text-pretty">
            {inline(
              'The same control plane, with a screen: the Scorecard and engine health on one panel, every run’s Act / Verify / Repair timeline as it happens, and the queue beside them. A local, single-user server — `alc ui`, no account, nothing leaves the machine.',
            )}
          </p>
        </div>
        <div className="mt-12">
          <WideRow>
            <Demo
              src={asset("/demo/alc-ui.mp4")}
              poster={asset("/demo/alc-ui.jpg")}
              width={1440}
              height={900}
              label="The alc web UI: dashboard, run list, and a finished run's timeline"
              caption="Dashboard to a finished run — the events are the ones the Assurance Loop recorded."
            />
          </WideRow>
        </div>
        <div className="mt-9 flex justify-center">
          <CtaLink cta={{ label: 'Read the Web UI guide', href: '/docs/web-ui/overview' }} variant="secondary" />
        </div>
      </Section>

      {/* ------------------------------------------------------------ Features */}
      <Section className="reveal border-t border-border">
        <div className="mx-auto max-w-3xl text-center">
          <SectionTitle>{c.features.heading}</SectionTitle>
        </div>
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {c.features.items.map((f, i) => {
            const Icon = FEATURE_ICONS[i % FEATURE_ICONS.length]
            return (
              <Card key={f.title} title={f.title} icon={<Icon size={18} />}>
                {inline(f.body)}
              </Card>
            )
          })}
        </div>
      </Section>

      {/* -------------------------------------------------------------- Ladder */}
      <Section className="reveal border-t border-border">
        <div className="mx-auto max-w-3xl text-center">
          <SectionTitle>{c.ladder.heading}</SectionTitle>
          <p className="mx-auto mt-4 text-[17px] leading-relaxed text-muted text-pretty">
            {inline(c.ladder.body)}
          </p>
        </div>
        <ol className="mt-12 grid gap-4 md:grid-cols-3">
          {c.ladder.rungs.map((rung, i) => (
            <li
              key={rung.title}
              className="rounded-lg border border-border bg-panel p-6"
              // Each rung sits higher than the last. The climb is the argument
              // of the section, so the layout makes it too.
              style={{ marginTop: `calc(${2 - i} * 1rem)` }}
            >
              <div className="flex items-baseline gap-2.5">
                <span className="font-mono text-xs text-accent">{i + 1}</span>
                <h3 className="text-[17px] font-medium text-primary">{rung.title}</h3>
              </div>
              <p className="mt-2.5 text-[15px] leading-relaxed text-muted">{inline(rung.body)}</p>
            </li>
          ))}
        </ol>
        {c.ladder.closing && (
          <p className="mx-auto mt-10 max-w-2xl text-center text-[17px] text-muted text-pretty">
            {inline(c.ladder.closing)}
          </p>
        )}
      </Section>

      {/* --------------------------------------------------------- Get started */}
      <Section className="reveal border-t border-border">
        <div className="mx-auto grid max-w-5xl gap-10 lg:grid-cols-2 lg:items-center">
          <div className="min-w-0">
            <SectionTitle>{c.start.heading}</SectionTitle>
            <Lede>{inline(c.start.body)}</Lede>
            <div className="mt-8 flex flex-wrap gap-3">
              {c.start.primary && <CtaLink cta={c.start.primary} variant="primary" />}
              {c.start.secondary && <CtaLink cta={c.start.secondary} variant="secondary" />}
            </div>
          </div>
          <div className="min-w-0">
            <Terminal
              lines={c.start.code.filter(Boolean).map((line) => {
                const [cmd, note] = line.split(/\s{2,}#\s*/)
                return { cmd: cmd.trim(), note: note?.trim() }
              })}
            />
            {c.start.note && (
              <p className="mt-3.5 text-sm leading-relaxed text-faint">{inline(c.start.note)}</p>
            )}
          </div>
        </div>
      </Section>
    </main>
  )
}
