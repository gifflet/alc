'use client'

// Install.tsx — the landing's primary call to action.
//
// Shaped as a sibling of <Terminal>: same border, same panel, same mono body.
// The difference is that the header strip, which on the Terminal holds three
// decorative dots, here does actual work — it holds the OS tabs. Same object,
// earning its chrome.
//
// macOS and Linux run the same command. They still get separate tabs, because a
// Linux user reading a tab labelled "macOS" has to guess whether it applies to
// them, and guessing is the thing this block exists to remove.
import { useEffect, useId, useRef, useState } from 'react'

type OsKey = 'macos' | 'linux' | 'windows'

const TARGETS: { key: OsKey; label: string; shell: string; command: string; script: string }[] = [
  {
    key: 'macos',
    label: 'macOS',
    shell: 'Terminal',
    command: 'curl -fsSL https://alc-runtime.vercel.app/install.sh | sh',
    script: '/install.sh',
  },
  {
    key: 'linux',
    label: 'Linux',
    shell: 'Terminal',
    command: 'curl -fsSL https://alc-runtime.vercel.app/install.sh | sh',
    script: '/install.sh',
  },
  {
    key: 'windows',
    label: 'Windows',
    shell: 'PowerShell',
    command: 'irm https://alc-runtime.vercel.app/install.ps1 | iex',
    script: '/install.ps1',
  },
]

/** Best guess at the visitor's OS, or null when there is nothing to go on.
 *
 *  Deliberately conservative: an unrecognised platform returns null and the
 *  server's default stands. A wrong tab is worse than an unsurprising one — the
 *  tabs are right there either way. */
export function detectOs(ua: string, platform?: string): OsKey | null {
  const s = `${platform ?? ''} ${ua}`.toLowerCase()
  if (/win/.test(s)) return 'windows'
  // Android is Linux-kernel but nobody installs a CLI on it, and iOS/iPadOS
  // report "mac" in some modes. Neither should steer the tab.
  if (/android|iphone|ipad|ipod/.test(s)) return null
  if (/linux|x11|cros/.test(s)) return 'linux'
  if (/mac/.test(s)) return 'macos'
  return null
}

export function Install() {
  // The server renders macOS. Detection can only run on the client, and doing it
  // during render would either differ from the server (a hydration error) or
  // force the whole block to be client-only, which would leave a visitor with
  // no JS looking at nothing. So: render a real, correct command, then adjust.
  const [active, setActive] = useState<OsKey>('macos')
  const [copied, setCopied] = useState(false)
  const [touched, setTouched] = useState(false)
  const tabsRef = useRef<(HTMLButtonElement | null)[]>([])
  const baseId = useId()

  useEffect(() => {
    if (touched) return
    const nav = navigator as Navigator & { userAgentData?: { platform?: string } }
    const guess = detectOs(nav.userAgent, nav.userAgentData?.platform ?? nav.platform)
    if (guess) setActive(guess)
  }, [touched])

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 2000)
    return () => clearTimeout(t)
  }, [copied])

  const current = TARGETS.find((t) => t.key === active) ?? TARGETS[0]

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(current.command)
      setCopied(true)
    } catch {
      // A denied clipboard is not an error worth shouting about: the command is
      // on screen and selectable. Saying nothing beats a red banner.
    }
  }

  // Arrow keys move between tabs, which is what a tablist is expected to do and
  // the only way to reach the other tabs without a pointer.
  const onKeyDown = (e: React.KeyboardEvent, index: number) => {
    const delta = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!delta) return
    e.preventDefault()
    const next = (index + delta + TARGETS.length) % TARGETS.length
    setTouched(true)
    setActive(TARGETS[next].key)
    tabsRef.current[next]?.focus()
  }

  return (
    <div className="mx-auto w-full max-w-[46rem] text-left">
      <div className="overflow-hidden rounded-md border border-border bg-panel shadow-[var(--elev-1)]">
        <div className="flex items-stretch justify-between gap-2 border-b border-border">
          <div role="tablist" aria-label="Operating system" className="flex items-stretch">
            {TARGETS.map((t, i) => {
              const selected = t.key === active
              return (
                <button
                  key={t.key}
                  ref={(el) => {
                    tabsRef.current[i] = el
                  }}
                  role="tab"
                  id={`${baseId}-tab-${t.key}`}
                  aria-selected={selected}
                  aria-controls={`${baseId}-panel`}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => {
                    setTouched(true)
                    setActive(t.key)
                  }}
                  onKeyDown={(e) => onKeyDown(e, i)}
                  className={`min-h-[44px] px-4 font-mono text-[12px] tracking-wide transition-colors duration-150 ${
                    selected
                      ? 'border-b-2 border-accent -mb-px text-primary'
                      : 'border-b-2 border-transparent text-faint hover:text-muted'
                  }`}
                >
                  {t.label}
                </button>
              )
            })}
          </div>

          <button
            type="button"
            onClick={copy}
            aria-label={`Copy the ${current.label} install command`}
            className="my-1 mr-1 flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center gap-1.5 rounded-xs px-3 font-mono text-[12px] text-faint transition-colors duration-150 hover:bg-hover hover:text-primary sm:min-h-[36px]"
          >
            <span aria-hidden>{copied ? '✓' : '⧉'}</span>
            <span className="hidden sm:inline">{copied ? 'copied' : 'copy'}</span>
          </button>
        </div>

        <div
          role="tabpanel"
          id={`${baseId}-panel`}
          aria-labelledby={`${baseId}-tab-${active}`}
          className="p-4 font-mono text-[12px] leading-relaxed sm:text-[13px]"
        >
          <div className="whitespace-pre-wrap break-words pl-[1.2em] -indent-[1.2em]">
            <span className="select-none text-faint">{current.key === 'windows' ? '> ' : '$ '}</span>
            <span className="text-primary">{current.command}</span>
          </div>
        </div>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-pretty text-faint">
        Installs uv if you do not have it, then <code className="font-mono">alc</code>, and puts it
        on your PATH. The same command updates you later —{' '}
        <a
          href={current.script}
          className="whitespace-nowrap text-muted underline decoration-border underline-offset-4 transition-colors hover:text-primary hover:decoration-current"
        >
          read the script
        </a>{' '}
        first if you would rather. Prefer not to pipe a script?{' '}
        <a
          href="/docs/getting-started/installation#installing-by-hand"
          className="text-muted underline decoration-border underline-offset-4 transition-colors hover:text-primary hover:decoration-current"
        >
          There is a one-line alternative
        </a>
        .
      </p>

      {/* Without JS the tabs cannot switch and the server's guess stands, so a
          Windows visitor would be looking at the macOS command — worse than
          seeing none, because it looks right. Spell both out. */}
      <noscript>
        <div className="mt-3 rounded-md border border-border bg-panel p-4 font-mono text-[12px] leading-relaxed">
          <div className="mb-2 font-sans text-sm text-faint">
            Tabs need JavaScript. Both commands, in full:
          </div>
          {TARGETS.filter((t, i) => TARGETS.findIndex((x) => x.command === t.command) === i).map(
            (t) => (
              <div key={t.key} className="mt-1.5 whitespace-pre-wrap break-words">
                <span className="select-none text-faint">
                  {t.key === 'windows' ? 'Windows > ' : 'macOS, Linux $ '}
                </span>
                <span className="text-primary">{t.command}</span>
              </div>
            ),
          )}
        </div>
      </noscript>

      {/* aria-live rather than a toast: the visual tick is already on the button,
          and this is the only way a screen reader learns the copy landed. */}
      <span aria-live="polite" className="sr-only">
        {copied ? `${current.label} install command copied` : ''}
      </span>
    </div>
  )
}
