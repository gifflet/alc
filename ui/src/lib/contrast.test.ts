import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { AA_BODY, AA_UI, contrast, ratio } from './contrast'

// vitest's root is ui/; `?raw` yields an empty module under `css: false`.
const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

/** Pull the token values declared inside a given CSS block. */
function tokens(blockStart: string): Record<string, string> {
  const from = css.indexOf(blockStart)
  if (from === -1) throw new Error(`block not found: ${blockStart}`)
  const to = css.indexOf('}', from)
  const body = css.slice(from, to)
  const out: Record<string, string> = {}
  for (const [, name, value] of body.matchAll(/--color-([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    out[name] = value
  }
  return out
}

const SURFACES = ['base', 'panel', 'raised', 'hover'] as const
const BODY_TEXT = ['primary', 'muted'] as const
const UI_TEXT = ['faint'] as const
const STATUS = ['accent', 'live', 'running', 'error', 'warn'] as const

/**
 * Pairs knowingly below AA body, kept rather than hidden: `hover` is a
 * transient state, the affected text is metadata, and links
 * carry an underline so colour is never the only signal. They must still clear
 * the 3:1 UI floor.
 */
const ACCEPTED_BODY_DEVIATIONS = new Set(['dark:muted:hover', 'dark:error:hover', 'dark:accent:hover'])

describe.each([
  ['dark', '@theme {'],
  ['light', ":root[data-theme='light']"],
])('%s palette', (theme, block) => {
  const t = tokens(block)

  it('declares each theme in exactly one block', () => {
    // Two blocks with the same selector is ambiguous — and it silently made this
    // suite read the wrong one when elevation was added in a second block.
    const occurrences = css.split(block).length - 1
    expect(occurrences, `${theme} is declared ${occurrences}x`).toBe(1)
  })

  it('declares every semantic role', () => {
    for (const name of [...SURFACES, ...BODY_TEXT, ...UI_TEXT, ...STATUS, 'border']) {
      expect(t[name], `${theme} is missing --color-${name}`).toBeDefined()
    }
  })

  it.each(BODY_TEXT)(`%s clears AA body on every surface`, (text) => {
    for (const surface of SURFACES) {
      const key = `${theme}:${text}:${surface}`
      const r = ratio(t[text], t[surface])
      if (ACCEPTED_BODY_DEVIATIONS.has(key)) {
        expect(r, `${key} is an accepted deviation but fell below the UI floor`).toBeGreaterThanOrEqual(AA_UI)
      } else {
        expect(r, `${key} is ${r}:1`).toBeGreaterThanOrEqual(AA_BODY)
      }
    }
  })

  it.each(UI_TEXT)('%s clears the UI floor on every surface', (text) => {
    for (const surface of SURFACES) {
      const r = ratio(t[text], t[surface])
      expect(r, `${theme}:${text}:${surface} is ${r}:1`).toBeGreaterThanOrEqual(AA_UI)
    }
  })

  it.each(STATUS)('%s stays readable on the main surfaces', (text) => {
    for (const surface of ['base', 'panel', 'raised'] as const) {
      const key = `${theme}:${text}:${surface}`
      const r = ratio(t[text], t[surface])
      const floor = ACCEPTED_BODY_DEVIATIONS.has(key) ? AA_UI : AA_BODY
      expect(r, `${key} is ${r}:1`).toBeGreaterThanOrEqual(floor)
    }
  })

  it('keeps the text hierarchy visually ordered', () => {
    // primary must read stronger than muted, muted stronger than faint.
    expect(contrast(t.primary, t.base)).toBeGreaterThan(contrast(t.muted, t.base))
    expect(contrast(t.muted, t.base)).toBeGreaterThan(contrast(t.faint, t.base))
  })
})

describe('the defect this guard exists for', () => {
  it('would fail the shipped-then-fixed dark faint', () => {
    // #5e646b on #1b1d1f measured 2.83:1 — below even the 3:1 UI floor.
    expect(ratio('#5e646b', '#1b1d1f')).toBeLessThan(AA_UI)
    // The replacement clears it.
    expect(ratio('#7d848b', '#1b1d1f')).toBeGreaterThanOrEqual(AA_UI)
  })
})
