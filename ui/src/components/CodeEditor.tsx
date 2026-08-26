// CodeEditor.tsx — Monaco editor, self-hosted and themed to the control room.
//
// Heavy on purpose: this module pulls in monaco-editor and its worker, so it is
// only ever imported via React.lazy (see SourceEditor) to keep it out of the
// initial bundle. The theme mirrors the design tokens in index.css.
import { useEffect, useRef } from 'react'
import Editor, { loader } from '@monaco-editor/react'
import type { Monaco } from '@monaco-editor/react'
import type { editor } from 'monaco-editor'
// Core editor only, plus the two Monarch grammars we actually use. Importing the
// full `monaco-editor` barrel would pull in ~90 languages and their workers; this
// keeps the lazy chunk small while still highlighting yaml + markdown.
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import 'monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution'
import 'monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import { useTheme } from '../app/useTheme'
import { expandHex } from '../lib/hex'

// Self-host monaco (offline: the built dist is served by `alc ui`) and give it a
// single generic worker — enough for the yaml/markdown highlighting we use.
self.MonacoEnvironment = { getWorker: () => new EditorWorker() }
loader.config({ monaco })

const THEME = 'alc'

/**
 * Read a design token from the document.
 *
 * Monaco cannot consume CSS custom properties, so its theme has to be built from
 * values. Reading them from :root keeps ONE source of truth: hardcoding them
 * meant the editor kept the old, contrast-failing colours after the palette was
 * fixed — and stayed dark on a light page.
 */
function tokenColor(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const raw = getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}`).trim()
  return raw ? expandHex(raw) || fallback : fallback
}

/** Strip the leading # — Monaco's token rules want a bare hex. */
function bare(value: string): string {
  return value.replace('#', '')
}

/** Define (or redefine) the editor theme from the CURRENT token values. */
function applyTheme(m: Monaco, isLight: boolean): void {
  const base = tokenColor('base', isLight ? '#ffffff' : '#1b1d1f')
  const panel = tokenColor('panel', isLight ? '#f1f2f4' : '#212427')
  const raised = tokenColor('raised', isLight ? '#f8f9fa' : '#26292c')
  const primary = tokenColor('primary', isLight ? '#1e2124' : '#d5d8dc')
  const faint = tokenColor('faint', '#7d848b')
  const muted = tokenColor('muted', isLight ? '#5a6066' : '#8b9096')
  const accent = tokenColor('accent', isLight ? '#1f66c9' : '#5794e6')
  const live = tokenColor('live', isLight ? '#1f7a3d' : '#5cc975')
  const running = tokenColor('running', isLight ? '#8a5d0a' : '#d9a343')

  m.editor.defineTheme(THEME, {
    base: isLight ? 'vs' : 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: bare(faint), fontStyle: 'italic' },
      { token: 'string', foreground: bare(live) },
      { token: 'number', foreground: bare(running) },
      { token: 'keyword', foreground: bare(accent) },
      { token: 'type', foreground: bare(accent) },
    ],
    colors: {
      'editor.background': base,
      'editor.foreground': primary,
      'editorLineNumber.foreground': faint,
      'editorLineNumber.activeForeground': muted,
      'editor.selectionBackground': `${accent}40`,
      'editor.lineHighlightBackground': panel,
      'editorCursor.foreground': accent,
      'editorGutter.background': base,
      'editorIndentGuide.background1': raised,
    },
  })
  m.editor.setTheme(THEME)
}

const OPTIONS: editor.IStandaloneEditorConstructionOptions = {
  fontFamily: "'JetBrains Mono Variable', ui-monospace, monospace",
  fontSize: 12,
  lineHeight: 19,
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  renderWhitespace: 'selection',
  tabSize: 2,
  automaticLayout: true,
  padding: { top: 8, bottom: 8 },
  smoothScrolling: true,
  overviewRulerLanes: 0,
}

export default function CodeEditor({
  value,
  onChange,
  language,
  readOnly = false,
}: {
  value: string
  onChange: (v: string) => void
  language: 'yaml' | 'markdown'
  readOnly?: boolean
}) {
  const theme = useTheme()
  const monacoRef = useRef<Monaco | null>(null)

  // Re-derive on every theme flip: defineTheme with the same name overwrites,
  // and setTheme re-applies it to the live editor.
  useEffect(() => {
    if (monacoRef.current) applyTheme(monacoRef.current, theme === 'light')
  }, [theme])

  return (
    <Editor
      value={value}
      language={language}
      theme={THEME}
      beforeMount={(m) => {
        monacoRef.current = m
        applyTheme(m, theme === 'light')
      }}
      onChange={(v) => onChange(v ?? '')}
      options={{ ...OPTIONS, readOnly }}
    />
  )
}
