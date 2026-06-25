import Editor from '@monaco-editor/react'
import { cn } from '@/lib/utils'
import type * as Monaco from 'monaco-editor'

// Define custom theme matching project's dark theme
const defineCustomTheme = (monaco: typeof Monaco) => {
  monaco.editor.defineTheme('conduit-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'string.json', foreground: 'f97316', fontStyle: 'italic' },
      { token: 'number.json', foreground: '22c55e' },
      { token: 'boolean.json', foreground: '3b82f6', fontStyle: 'bold' },
      { token: 'null.json', foreground: 'ef4444', fontStyle: 'bold' },
      { token: 'key.json', foreground: 'a78bfa' },
      { token: 'delimiter.json', foreground: '94a3b8' },
    ],
    colors: {
      'editor.background': '#0a0e17',
      'editor.foreground': '#f1f5f9',
      'editor.lineHighlightBackground': '#1e293b',
      'editorLineNumber.foreground': '#64748b',
      'editorLineNumber.activeForeground': '#f1f5f9',
      'editor.selectionBackground': '#4c1d95',
      'editor.inactiveSelectionBackground': '#4c1d9555',
      'editorCursor.foreground': '#a78bfa',
      'editorBracketMatch.background': '#4c1d95',
      'editorBracketMatch.border': '#a78bfa',
      'editorIndentGuide.background': '#1e293b',
      'editorIndentGuide.activeBackground': '#475569',
      'editorOverviewRuler.border': '#1e293b',
      'editorWidget.background': '#1e293b',
      'editorWidget.border': '#475569',
      'editorSuggestWidget.background': '#1e293b',
      'editorSuggestWidget.border': '#475569',
      'editorSuggestWidget.foreground': '#f1f5f9',
      'editorSuggestWidget.selectedBackground': '#4c1d95',
      'editorSuggestWidget.highlightForeground': '#a78bfa',
      'errorForeground': '#ef4444',
    },
  })
}

interface JsonEditorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
  className?: string
  minRows?: number
}

export function JsonEditor({
  value,
  onChange,
  placeholder = '',
  disabled = false,
  className,
}: JsonEditorProps) {
  const handleEditorDidMount = (editor: Monaco.editor.IStandaloneCodeEditor, monaco: typeof Monaco) => {
    defineCustomTheme(monaco)
    monaco.editor.setTheme('conduit-dark')
  }

  return (
    <div className={cn('relative', className)}>
      <Editor
        height="400px"
        defaultLanguage="json"
        value={value}
        onChange={(newValue) => onChange(newValue || '')}
        beforeMount={defineCustomTheme}
        onMount={handleEditorDidMount}
        options={{
          minimap: { enabled: false },
          fontSize: 14,
          fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
          lineNumbers: 'on',
          scrollBeyondLastLine: false,
          automaticLayout: true,
          tabSize: 2,
          formatOnPaste: true,
          formatOnType: true,
          readOnly: disabled,
          wordWrap: 'on',
          folding: true,
          bracketPairColorization: { enabled: true },
          guides: {
            bracketPairs: true,
            indentation: true,
          },
        }}
      />
    </div>
  )
}
