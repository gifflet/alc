// PrimerForm.tsx — Structured editor over a Primer's plain Markdown body
// (.alc/primers/<name>.md).
//
// A Primer has no front-matter or schema: models.py carries no Primer model,
// and `primer.load_primer` (src/alc/primer.py) just reads the file's text
// verbatim. The scaffold (authoring.py) always starts a Primer with a leading
// `# <name>` heading, so that is the one thing worth splitting into its own
// field; everything else — the rest of the body, in whatever shape the
// operator gave it — is a single textarea, edited by plain string
// concatenation so nothing below the heading is ever touched. No YAML
// Document is involved; the body IS the unmodeled content.
import { Info } from 'lucide-react'
import { Field, TextArea, TextInput } from '../../components/fields'

const TITLE_RE = /^# (.*)\n?/

export function PrimerForm({ value, onChange }: { value: string; onChange: (raw: string) => void }) {
  const match = value.match(TITLE_RE)
  const title = match ? match[1] : ''
  const rest = match ? value.slice(match[0].length) : value

  const setTitle = (v: string) => onChange(`# ${v}\n${rest}`)
  const setBody = (v: string) => onChange(match ? `# ${title}\n${v}` : v)

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <p className="flex items-center gap-1.5 text-[11px] text-faint">
        <Info className="h-3.5 w-3.5" />A Primer has no schema — only the leading heading is split out here; the
        rest is free text.
      </p>

      {match && (
        <Field label="Title">
          <TextInput value={title} onChange={setTitle} />
        </Field>
      )}

      <Field label="Body">
        <TextArea value={rest} onChange={setBody} rows={18} />
      </Field>
    </div>
  )
}
