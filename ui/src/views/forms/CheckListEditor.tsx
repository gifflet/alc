// CheckListEditor.tsx — Editor for a `list[Check]` node at some path in a
// parsed `yaml` Document. A Check declares exactly one of command/shell/metric
// (models.Check); switching the row's mode REPLACES the shape rather than
// adding to it. Shared by BlueprintForm's top-level `checks:` and each named
// bucket of Manifest's `check_sets:`.
import type { Document } from 'yaml'
import { Plus, Trash2 } from 'lucide-react'
import { safeDeleteIn } from '../../lib/yamlDoc'

type CheckMode = 'command' | 'shell' | 'metric'
type Direction = 'lower_is_better' | 'higher_is_better'

interface CheckRow {
  name: string
  mode: CheckMode
  value: string
  direction: Direction
  tolerancePct: number
  flaky: number
}

type Path = (string | number)[]

function readArgvLike(node: unknown): string {
  const seq = node as { toJSON?: () => unknown } | null
  if (seq && typeof seq === 'object' && typeof seq.toJSON === 'function') {
    const v = seq.toJSON()
    return Array.isArray(v) ? v.join(' ') : String(v ?? '')
  }
  return node == null ? '' : String(node)
}

function readChecks(doc: Document, path: Path): CheckRow[] {
  const seq = doc.getIn(path) as { items?: unknown[] } | null
  if (!seq?.items) return []
  return seq.items.map((_, i) => {
    const at = (...rest: Path) => doc.getIn([...path, i, ...rest])
    const name = String(at('name') ?? '')
    const direction = (at('direction') as Direction) || 'lower_is_better'
    const tolerancePct = Number(at('tolerance_pct') ?? 0)
    const flaky = Number(at('flaky') ?? 0)
    if (at('metric') != null) {
      return { name, mode: 'metric', value: readArgvLike(at('metric')), direction, tolerancePct, flaky }
    }
    if (at('shell') != null) {
      return { name, mode: 'shell', value: String(at('shell')), direction, tolerancePct, flaky }
    }
    return { name, mode: 'command', value: readArgvLike(at('command')), direction, tolerancePct, flaky }
  })
}

export function CheckListEditor({
  doc,
  path,
  update,
}: {
  doc: Document
  path: Path
  update: (mutate: (d: Document) => void) => void
}) {
  const checks = readChecks(doc, path)

  const setCheck = (i: number, row: CheckRow) =>
    update((d) => {
      d.setIn([...path, i, 'name'], row.name)
      safeDeleteIn(d, [...path, i, 'command'])
      safeDeleteIn(d, [...path, i, 'shell'])
      safeDeleteIn(d, [...path, i, 'metric'])
      if (row.mode === 'shell') {
        d.setIn([...path, i, 'shell'], row.value)
      } else {
        const argv = row.value.trim() ? row.value.trim().split(/\s+/) : ['true']
        d.setIn([...path, i, row.mode === 'metric' ? 'metric' : 'command'], argv)
      }
      if (row.mode === 'metric') {
        d.setIn([...path, i, 'direction'], row.direction)
        d.setIn([...path, i, 'tolerance_pct'], row.tolerancePct)
      } else {
        safeDeleteIn(d, [...path, i, 'direction'])
        safeDeleteIn(d, [...path, i, 'tolerance_pct'])
      }
      if (row.flaky) d.setIn([...path, i, 'flaky'], row.flaky)
      else safeDeleteIn(d, [...path, i, 'flaky'])
    })

  const addCheck = () =>
    update((d) => {
      const seq = d.getIn(path) as { add?: (v: unknown) => void } | null
      const item = { name: 'check', command: ['true'] }
      if (seq?.add) seq.add(item)
      else d.setIn(path, [item])
    })

  const removeCheck = (i: number) => update((d) => d.deleteIn([...path, i]))

  return (
    <div className="flex flex-col gap-2">
      {checks.length === 0 ? (
        <p className="text-[length:var(--ui-text-body)] text-faint">No checks.</p>
      ) : (
        checks.map((row, i) => (
          <div key={i} className="flex flex-col gap-1.5 rounded-panel border border-border p-2">
            <div className="flex items-center gap-2">
              <input
                value={row.name}
                onChange={(e) => setCheck(i, { ...row, name: e.target.value })}
                placeholder="name"
                aria-label="Check name"
                spellCheck={false}
                className="w-28 rounded-panel border border-border bg-base px-2 py-1 text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
              />
              <select
                value={row.mode}
                onChange={(e) => setCheck(i, { ...row, mode: e.target.value as CheckMode })}
                aria-label="Check mode"
                className="rounded-panel border border-border bg-base px-2 py-1 text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
              >
                <option value="command">command</option>
                <option value="shell">shell</option>
                <option value="metric">metric</option>
              </select>
              <input
                value={row.value}
                onChange={(e) => setCheck(i, { ...row, value: e.target.value })}
                placeholder={
                  row.mode === 'command' ? 'pytest -q' : row.mode === 'shell' ? 'test -z "$(git diff)"' : 'scripts/bench.py'
                }
                aria-label="Check value"
                spellCheck={false}
                className="flex-1 rounded-panel border border-border bg-base px-2 py-1 font-mono text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
              />
              <button
                type="button"
                aria-label={`Remove ${row.name}`}
                onClick={() => removeCheck(i)}
                className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint hover:text-error"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="flex items-center gap-3 pl-1">
              {row.mode === 'metric' && (
                <>
                  <label className="flex items-center gap-1 text-[length:var(--ui-text-label)] text-faint">
                    direction
                    <select
                      value={row.direction}
                      onChange={(e) => setCheck(i, { ...row, direction: e.target.value as Direction })}
                      aria-label="Metric direction"
                      className="rounded-panel border border-border bg-base px-1.5 py-0.5 text-[length:var(--ui-text-label)] text-primary outline-none focus:border-accent"
                    >
                      <option value="lower_is_better">lower_is_better</option>
                      <option value="higher_is_better">higher_is_better</option>
                    </select>
                  </label>
                  <label className="flex items-center gap-1 text-[length:var(--ui-text-label)] text-faint">
                    tolerance %
                    <input
                      type="number"
                      value={row.tolerancePct}
                      onChange={(e) => setCheck(i, { ...row, tolerancePct: Number(e.target.value) })}
                      aria-label="Tolerance percent"
                      className="w-16 rounded-panel border border-border bg-base px-1.5 py-0.5 text-[length:var(--ui-text-label)] text-primary outline-none focus:border-accent"
                    />
                  </label>
                </>
              )}
              <label className="flex items-center gap-1 text-[length:var(--ui-text-label)] text-faint">
                flaky reruns
                <input
                  type="number"
                  value={row.flaky}
                  onChange={(e) => setCheck(i, { ...row, flaky: Number(e.target.value) })}
                  aria-label="Flaky reruns"
                  className="w-14 rounded-panel border border-border bg-base px-1.5 py-0.5 text-[length:var(--ui-text-label)] text-primary outline-none focus:border-accent"
                />
              </label>
            </div>
          </div>
        ))
      )}
      <button
        type="button"
        onClick={addCheck}
        className="flex w-fit items-center gap-1 rounded-panel border border-border px-2 py-1 text-[length:var(--ui-text-label)] text-muted hover:bg-hover hover:text-primary"
      >
        <Plus className="h-3 w-3" />
        Add check
      </button>
    </div>
  )
}
