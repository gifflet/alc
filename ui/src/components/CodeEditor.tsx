// CodeEditor.tsx — Monaco editor, self-hosted and themed to the control room.
//
// Heavy on purpose: this module pulls in monaco-editor and its worker, so it is
// only ever imported via React.lazy (see SourceEditor) to keep it out of the
// initial bundle. The theme mirrors the design tokens in index.css.
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

// Self-host monaco (offline: the built dist is served by `alc ui`) and give it a
// single generic worker — enough for the yaml/markdown highlighting we use.
self.MonacoEnvironment = { getWorker: () => new EditorWorker() }
loader.config({ monaco })

const THEME = 'alc-dark'

function defineTheme(m: Monaco): void {
  m.editor.defineTheme(THEME, {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '5e646b', fontStyle: 'italic' },
      { token: 'string', foreground: '5cc975' },
      { token: 'number', foreground: 'd9a343' },
      { token: 'keyword', foreground: '3d7edb' },
      { token: 'type', foreground: '3d7edb' },
    ],
    colors: {
      'editor.background': '#1b1d1f',
      'editor.foreground': '#d5d8dc',
      'editorLineNumber.foreground': '#5e646b',
      'editorLineNumber.activeForeground': '#8b9096',
      'editor.selectionBackground': '#3d7edb40',
      'editor.lineHighlightBackground': '#212427',
      'editorCursor.foreground': '#3d7edb',
      'editorGutter.background': '#1b1d1f',
      'editorIndentGuide.background1': '#26292c',
    },
  })
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
  return (
    <Editor
      value={value}
      language={language}
      theme={THEME}
      beforeMount={defineTheme}
      onChange={(v) => onChange(v ?? '')}
      options={{ ...OPTIONS, readOnly }}
    />
  )
}
