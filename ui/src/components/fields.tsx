// fields.tsx — Compact labelled form controls for dialogs and settings forms.
import type { ReactNode } from 'react'

const INPUT =
  'w-full rounded-panel border border-border bg-base px-2 py-1.5 text-[12px] text-primary outline-none focus:border-accent'

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wide text-faint">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-faint">{hint}</span>}
    </label>
  )
}

export function TextInput({
  value,
  onChange,
  placeholder,
  mono,
  autoFocus,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  mono?: boolean
  autoFocus?: boolean
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      spellCheck={false}
      autoFocus={autoFocus}
      className={`${INPUT} ${mono ? 'font-mono' : ''}`}
    />
  )
}

export function TextArea({
  value,
  onChange,
  rows = 4,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  rows?: number
  placeholder?: string
}) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      rows={rows}
      placeholder={placeholder}
      spellCheck={false}
      className={`${INPUT} resize-y`}
    />
  )
}

export function NumberInput({
  value,
  onChange,
  placeholder,
}: {
  value: number | ''
  onChange: (v: number | '') => void
  placeholder?: string
}) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
      placeholder={placeholder}
      className={`${INPUT} tabular font-mono`}
    />
  )
}

export function Select({
  value,
  onChange,
  options,
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={INPUT}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

export function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <label className="flex items-center gap-2 text-[12px] text-primary">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 accent-accent"
      />
      {label}
    </label>
  )
}
