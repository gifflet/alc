import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * The audit that motivated move 8, turned into a guard.
 *
 * Before the sweep: 154 `text-[11px]`, 108 `text-[12px]`, 90 components on a 3px
 * radius, and a 1px rule under every row. Those numbers came from grep — so grep
 * is what keeps them from coming back.
 */
const SRC = resolve(process.cwd(), 'src')

function sourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(full))
    } else if (/\.tsx?$/.test(entry) && !entry.includes('.test.')) {
      out.push(full)
    }
  }
  return out
}

const FILES = sourceFiles(SRC)
const read = (f: string) => readFileSync(f, 'utf8')

/** Sizes that must come from a token; 14px+ are deliberate one-offs. */
const FORBIDDEN_SIZES = ['9px', '10px', '11px', '12px', '13px']

describe('design system', () => {
  it('has files to check (the walker itself works)', () => {
    expect(FILES.length).toBeGreaterThan(40)
  })

  it.each(FORBIDDEN_SIZES)('uses no hardcoded text-[%s]', (size) => {
    const offenders = FILES.filter((f) => read(f).includes(`text-[${size}]`)).map((f) =>
      f.replace(SRC, ''),
    )
    expect(offenders, `use text-[length:var(--ui-text-*)] instead`).toEqual([])
  })

  it('never re-introduces the hard per-row rule', () => {
    // border-border/60 under every row is what made tables read as spreadsheets.
    const offenders = FILES.filter((f) => read(f).includes('border-border/60')).map((f) =>
      f.replace(SRC, ''),
    )
    expect(offenders).toEqual([])
  })

  it('never re-introduces a fixed 28px row', () => {
    const offenders = FILES.filter((f) => read(f).includes('h-[28px]')).map((f) => f.replace(SRC, ''))
    expect(offenders, 'row height comes from --ui-row-h').toEqual([])
  })

  it('keeps the shared radius off the old 3px', () => {
    const css = readFileSync(join(SRC, 'index.css'), 'utf8')
    const match = css.match(/--radius-panel: (\d+)px;/)
    expect(match).not.toBeNull()
    expect(Number(match![1])).toBeGreaterThanOrEqual(6)
  })

  it('declares the full radius and elevation scales', () => {
    const css = readFileSync(join(SRC, 'index.css'), 'utf8')
    for (const token of ['--radius-xs', '--radius-sm', '--radius-md', '--radius-lg']) {
      expect(css, `${token} missing`).toContain(token)
    }
    for (const token of ['--elev-1', '--elev-2', '--elev-3']) {
      expect(css, `${token} missing`).toContain(token)
    }
  })

  it('keeps raw hex colours out of component code', () => {
    // The theme cannot reach a literal; CodeEditor is the one exception (Monaco
    // cannot read CSS custom properties) and it derives them at runtime.
    const allowed = ['/lib/contrast.ts', '/lib/hex.ts', '/components/CodeEditor.tsx']
    const offenders = FILES.filter((f) => /#[0-9a-fA-F]{6}\b/.test(read(f)))
      .map((f) => f.replace(SRC, ''))
      .filter((f) => !allowed.includes(f))
    expect(offenders).toEqual([])
  })
})

describe('motion', () => {
  const readCss = () => readFileSync(join(SRC, 'index.css'), 'utf8')

  it('honours prefers-reduced-motion', () => {
    const css = readCss()
    // alc-pulse runs infinitely on every live indicator; alc-fade-in fires on
    // every tree row. Without this block a busy control room is in constant
    // motion for someone who asked the system to stop exactly that.
    expect(css).toContain('prefers-reduced-motion: reduce')
  })

  it('disables the infinite pulse under that preference, not just shortens it', () => {
    const css = readCss()
    const block = css.slice(css.indexOf('prefers-reduced-motion: reduce'))
    expect(block).toMatch(/\.alc-pulse[\s\S]{0,120}animation:\s*none/)
  })
})
