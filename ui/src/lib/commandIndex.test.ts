import { describe, expect, it } from 'vitest'
import { groupCommands, matchStrength, rankCommands } from './commandIndex'
import type { Command } from './commandIndex'

const cmd = (id: string, kind: Command['kind'], label: string): Command => ({
  id,
  kind,
  label,
  run: () => {},
})

describe('matchStrength', () => {
  it('ranks an exact prefix highest', () => {
    expect(matchStrength('chore', 'ch')).toBe('prefix')
  })

  it('recognises a word boundary inside the label', () => {
    expect(matchStrength('run configurations', 'conf')).toBe('word')
  })

  it('falls back to substring, then subsequence', () => {
    expect(matchStrength('deps-refresh', 'efre')).toBe('substring')
    expect(matchStrength('deps-refresh', 'dpr')).toBe('subsequence')
  })

  it('returns null when nothing matches', () => {
    expect(matchStrength('chore', 'zzz')).toBeNull()
  })

  it('matches everything on an empty query', () => {
    expect(matchStrength('anything', '')).toBe('prefix')
  })

  it('is case-insensitive', () => {
    expect(matchStrength('Fleet', 'fl')).toBe('prefix')
  })

  it('does not treat query punctuation as a regex', () => {
    // A naive word-boundary regex would throw on an unbalanced bracket.
    expect(() => matchStrength('run [beta]', '[be')).not.toThrow()
  })
})

describe('rankCommands', () => {
  it('puts a prefix match above a subsequence match', () => {
    // 'a-b-c' only matches 'abc' as a subsequence; 'abc-thing' matches as a
    // prefix. (Note "deps-refresh" WOULD be a prefix match for "dep" — the
    // hierarchy only shows up with a genuinely weaker match.)
    const out = rankCommands(
      [cmd('weak', 'blueprint', 'a-b-c'), cmd('strong', 'blueprint', 'abc-thing')],
      'abc',
    )
    expect(out.map((c) => c.id)).toEqual(['strong', 'weak'])
  })

  it('puts a word-boundary match above a bare substring', () => {
    const out = rankCommands(
      [cmd('sub', 'blueprint', 'xxconfig'), cmd('word', 'blueprint', 'run config')],
      'config',
    )
    expect(out.map((c) => c.id)).toEqual(['word', 'sub'])
  })

  it('breaks a tie by kind, so views beat raw data', () => {
    const out = rankCommands([cmd('r', 'run', 'queue-thing'), cmd('v', 'view', 'queue')], 'queue')
    expect(out[0].id).toBe('v')
  })

  it('keeps the supplied order for an equal match and kind', () => {
    const out = rankCommands([cmd('1', 'run', 'run-a'), cmd('2', 'run', 'run-b')], 'run')
    expect(out.map((c) => c.id)).toEqual(['1', '2'])
  })

  it('drops non-matches entirely', () => {
    const out = rankCommands([cmd('a', 'view', 'fleet'), cmd('b', 'view', 'queue')], 'fl')
    expect(out.map((c) => c.id)).toEqual(['a'])
  })

  it('returns everything for an empty query', () => {
    const all = [cmd('a', 'view', 'fleet'), cmd('b', 'run', 'run-a')]
    expect(rankCommands(all, '')).toHaveLength(2)
  })
})

describe('groupCommands', () => {
  it('groups in the documented kind order', () => {
    const groups = groupCommands([
      cmd('r', 'run', 'run-a'),
      cmd('v', 'view', 'fleet'),
      cmd('b', 'blueprint', 'chore'),
    ])
    expect(groups.map((g) => g.kind)).toEqual(['view', 'blueprint', 'run'])
  })

  it('omits empty groups', () => {
    expect(groupCommands([cmd('v', 'view', 'fleet')]).map((g) => g.kind)).toEqual(['view'])
  })
})
