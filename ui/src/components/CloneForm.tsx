// CloneForm.tsx — Clone a repository that is not on this machine yet.
//
// The clone runs on the host, through the git binary, which is how every other
// git operation in ALC works — and it means the operator's SSH agent and
// credential helpers apply without being reimplemented here.
//
// Progress is followed rather than awaited. A clone of a large repository takes
// minutes, and a request that blocks for minutes is one a proxy eventually
// kills; the POST returns an exec id and the output arrives over the socket.
import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Download, FolderSearch, Loader2 } from 'lucide-react'
import { ApiError, api } from '../api/client'
import { useWs } from '../ws/WsProvider'
import { DirectoryBrowser } from './DirectoryBrowser'
import { ActionButton } from './ActionButton'

export function CloneForm({ onCloned }: { onCloned: (path: string) => void }) {
  const [url, setUrl] = useState('')
  const [parent, setParent] = useState('')
  const [name, setName] = useState('')
  const [browsing, setBrowsing] = useState(false)
  const [execId, setExecId] = useState<string | null>(null)
  const [destination, setDestination] = useState<string | null>(null)
  const [lines, setLines] = useState<string[]>([])
  const [failed, setFailed] = useState<string | null>(null)
  const { client } = useWs()

  const start = useMutation({
    mutationFn: () => api.cloneRepository(url.trim(), parent.trim(), name.trim() || undefined),
    onSuccess: (started) => {
      setExecId(started.exec_id)
      setDestination(started.destination)
      setLines([])
      setFailed(null)
    },
  })

  // Clone execs are published with no project id, which the bus treats as
  // global — the only scope that reaches a client not yet inside a project.
  useEffect(() => {
    if (!execId || !client) return
    return client.on((msg) => {
      if (msg.type === 'exec_output' && msg.exec_id === execId) {
        setLines((current) => [...current.slice(-40), msg.line])
      } else if (msg.type === 'exec_finished' && msg.exec_id === execId) {
        setExecId(null)
        if (msg.exit_code === 0 && destination) onCloned(destination)
        else setFailed(`git exited with code ${msg.exit_code}`)
      }
    })
  }, [execId, client, destination, onCloned])

  const startError =
    start.error instanceof ApiError ? start.error.message : start.error ? String(start.error) : null
  const busy = start.isPending || execId !== null

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (url.trim() && parent.trim() && !busy) start.mutate()
      }}
    >
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://github.com/owner/repo.git"
        aria-label="Repository URL"
        spellCheck={false}
        disabled={busy}
        className="rounded-panel border border-border bg-base min-h-[var(--ui-control-h)] px-2 font-mono text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent disabled:opacity-50"
      />

      <div className="flex gap-2">
        <input
          value={parent}
          onChange={(e) => setParent(e.target.value)}
          placeholder="clone into which directory?"
          aria-label="Parent directory"
          spellCheck={false}
          disabled={busy}
          className="min-w-0 flex-1 rounded-panel border border-border bg-base min-h-[var(--ui-control-h)] px-2 font-mono text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent disabled:opacity-50"
        />
        <ActionButton
          onClick={() => setBrowsing((b) => !b)}
          disabled={busy}
          aria-expanded={browsing}
          tone="ghost"
          size="md"
          className="shrink-0"
        >
          <FolderSearch className="h-3.5 w-3.5" />
          {browsing ? 'Hide' : 'Browse'}
        </ActionButton>
      </div>

      {browsing && (
        <DirectoryBrowser
          onPick={(picked) => {
            setParent(picked)
            setBrowsing(false)
          }}
        />
      )}

      <div className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="folder name (defaults to the repo name)"
          aria-label="Folder name"
          disabled={busy}
          className="min-w-0 flex-1 rounded-panel border border-border bg-base min-h-[var(--ui-control-h)] px-2 text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent disabled:opacity-50"
        />
        <ActionButton
          type="submit"
          disabled={!url.trim() || !parent.trim() || busy}
          tone="accent"
          size="md"
          className="shrink-0"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          {execId ? 'Cloning…' : 'Clone'}
        </ActionButton>
      </div>

      {(startError || failed) && (
        <p className="text-[length:var(--ui-text-label)] text-error">{startError ?? failed}</p>
      )}

      {lines.length > 0 && (
        // git writes progress to stderr; showing it verbatim is more use than a
        // spinner, because "Receiving objects: 47%" answers the question a
        // spinner leaves open.
        <pre className="max-h-32 overflow-y-auto rounded-panel border border-border bg-base p-2 font-mono text-[length:var(--ui-text-label)] text-muted">
          {lines.join('\n')}
        </pre>
      )}
    </form>
  )
}
