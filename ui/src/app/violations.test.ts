import { describe, expect, it } from 'vitest'
import { violationTarget } from './violations'
import type { Violation } from '../api/types'

const v = (rule: string, message: string, severity = 'error'): Violation => ({ rule, severity, message })

describe('violationTarget', () => {
  it('points a blueprint rule at its blueprint source', () => {
    const arg = violationTarget(
      v('blueprint_has_checks', "Blueprint 'chore' declares no checks — an Assurance Loop…"),
    )
    expect(arg?.target).toEqual({ type: 'source', resource: 'blueprints', name: 'chore' })
    expect(arg?.title).toBe('chore.md')
  })

  it('points flow / specialist / loop rules at their sources', () => {
    expect(violationTarget(v('flow-stage', "Flow 'ship' stage references…"))?.target).toEqual({
      type: 'source',
      resource: 'flows',
      name: 'ship',
    })
    expect(
      violationTarget(v('x', "Loop 'nightly' replenish references specialist 'r'…"))?.target,
    ).toEqual({ type: 'source', resource: 'loops', name: 'nightly' })
  })

  it('points a prompt-override rule at its prompt file', () => {
    expect(
      violationTarget(v('prompt-override-placeholders', "Prompt override 'act' is missing…"))?.target,
    ).toEqual({ type: 'source', resource: 'prompts', name: 'act' })
  })

  it('prefers the blueprint when a blueprint references a missing prompt', () => {
    const arg = violationTarget(
      v('prompt-include-resolves', "Blueprint 'chore' references prompt '{{prompt:x}}' which…"),
    )
    expect(arg?.target).toEqual({ type: 'source', resource: 'blueprints', name: 'chore' })
  })

  it('points engine / tier rules at the manifest', () => {
    expect(
      violationTarget(v('default_engine_resolvable', "manifest.default_engine 'x' is not declared…"))
        ?.target,
    ).toEqual({ type: 'source', resource: 'manifest', name: 'manifest' })
    expect(
      violationTarget(v('compute_tier_maps_engine', "Compute Tier 'standard' does not map engine 'm'."))
        ?.target,
    ).toEqual({ type: 'source', resource: 'manifest', name: 'manifest' })
  })

  it('returns null when no source can be identified', () => {
    expect(violationTarget(v('mystery', 'something opaque happened'))).toBeNull()
  })
})
