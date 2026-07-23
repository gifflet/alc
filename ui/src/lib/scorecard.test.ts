import { describe, expect, it } from 'vitest'
import { formatNetLines, scorecardHistory } from './scorecard'
import type { DoneTask, FlowReport } from '../api/types'

const report = (span: number, success: boolean): FlowReport => ({
  flow: 'ship',
  engine: 'mock',
  success,
  stages: [],
  scorecard: { span, passes: span, streak: 1, touch: 0 },
  commit_sha: null,
})

const done = (stem: string, mtime: number, r: FlowReport | null): DoneTask => ({
  stem,
  mtime,
  task: null,
  report: r,
  outstanding: false,
})

describe('scorecardHistory', () => {
  it('keeps only reported tasks, oldest to newest', () => {
    const points = scorecardHistory([
      done('c', 3, report(2, true)),
      done('a', 1, report(1, false)),
      done('b', 2, null),
    ])
    expect(points.map((p) => p.stem)).toEqual(['a', 'c'])
    expect(points[0]).toMatchObject({ span: 1, success: false })
    expect(points[1]).toMatchObject({ span: 2, success: true })
  })

  it('caps to the last N reports', () => {
    const tasks = Array.from({ length: 20 }, (_, i) => done(`t${i}`, i, report(i, true)))
    const points = scorecardHistory(tasks, 5)
    expect(points).toHaveLength(5)
    expect(points.map((p) => p.stem)).toEqual(['t15', 't16', 't17', 't18', 't19'])
  })

  it('returns an empty list when nothing is reported', () => {
    expect(scorecardHistory([done('a', 1, null)])).toEqual([])
  })
})

describe('formatNetLines', () => {
  it('signs a negative total with a minus sign', () => {
    expect(formatNetLines(-142)).toBe('−142')
  })

  it('signs a positive total with a plus sign', () => {
    expect(formatNetLines(58)).toBe('+58')
  })

  it('renders a zero total without a sign', () => {
    expect(formatNetLines(0)).toBe('0')
  })

  it('returns null for a missing or absent total (no diffstat data)', () => {
    expect(formatNetLines(null)).toBeNull()
    expect(formatNetLines(undefined)).toBeNull()
  })
})
