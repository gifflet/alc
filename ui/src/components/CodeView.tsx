// CodeView.tsx — Read-only source viewer with light, dependency-free highlight.
//
// A full tokenizer would be over-engineering for a viewer: a per-line pass that
// tints YAML keys/strings/comments and Markdown headings/lists reads well in
// dark and stays trivially safe (React spans, never innerHTML).
import type { ReactNode } from 'react'

export type CodeLang = 'yaml' | 'markdown' | 'diff' | 'text'

/** Infer a language from a file suffix (.md -> markdown, .yaml -> yaml). */
export function langForName(name: string): CodeLang {
  if (name.endsWith('.md')) return 'markdown'
  if (name.endsWith('.yaml') || name.endsWith('.yml')) return 'yaml'
  return 'text'
}

function highlightYaml(line: string): ReactNode {
  const trimmed = line.trimStart()
  if (trimmed.startsWith('#')) return <span className="text-faint">{line}</span>
  const m = line.match(/^(\s*(?:-\s+)?)([\w.$-]+)(:)(.*)$/)
  if (m) {
    return (
      <>
        <span>{m[1]}</span>
        <span className="text-accent">{m[2]}</span>
        <span className="text-faint">{m[3]}</span>
        <span className="text-live">{m[4]}</span>
      </>
    )
  }
  return <span>{line}</span>
}

function highlightMarkdown(line: string): ReactNode {
  if (/^#{1,6}\s/.test(line)) return <span className="font-semibold text-primary">{line}</span>
  if (/^\s*[-*]\s/.test(line)) return <span className="text-muted">{line}</span>
  if (/^\s*(---|```)/.test(line)) return <span className="text-faint">{line}</span>
  return <span className="text-muted">{line}</span>
}

function highlightDiff(line: string): ReactNode {
  // File/metadata headers first — they also start with +/-/@, so they must be
  // matched BEFORE the single-char add/del/hunk cases below.
  if (line.startsWith('+++') || line.startsWith('---')) return <span className="text-faint">{line}</span>
  if (line.startsWith('diff ') || line.startsWith('index ')) return <span className="text-faint">{line}</span>
  if (line.startsWith('@@')) return <span className="text-accent">{line}</span>
  if (line.startsWith('+')) return <span className="text-live">{line}</span>
  if (line.startsWith('-')) return <span className="text-error">{line}</span>
  return <span className="text-muted">{line}</span>
}

function highlight(line: string, lang: CodeLang): ReactNode {
  if (lang === 'yaml') return highlightYaml(line)
  if (lang === 'markdown') return highlightMarkdown(line)
  if (lang === 'diff') return highlightDiff(line)
  return <span>{line}</span>
}

export function CodeView({ code, lang }: { code: string; lang: CodeLang }) {
  const lines = code.replace(/\n$/, '').split('\n')
  return (
    <div className="h-full overflow-auto bg-base font-mono text-[length:var(--ui-text-body)] leading-[1.55]">
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, i) => (
            <tr key={i}>
              <td className="w-10 select-none border-r border-border px-2 text-right align-top text-faint">
                {i + 1}
              </td>
              <td className="whitespace-pre px-3 align-top text-primary">
                {highlight(line, lang)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
