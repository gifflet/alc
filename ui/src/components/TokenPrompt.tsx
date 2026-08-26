// TokenPrompt.tsx — Shown when the server rejected (or was never given) a token.
//
// It replaces the whole app rather than decorating a view: with no credential
// there is no project state to show, and showing a view's empty state instead
// would be a lie about the project.
import { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { authStore } from '../app/authStore'
import { setToken } from '../app/token'

export function TokenPrompt() {
  const [value, setValue] = useState('')

  function submit(event: React.FormEvent): void {
    event.preventDefault()
    const token = value.trim()
    if (!token) return
    setToken(token)
    authStore.setUnauthorized(false)
    // A full reload is the simplest correct reset: every query refetches with
    // the new credential and no stale error state survives.
    window.location.reload()
  }

  return (
    <div className="flex h-full items-center justify-center bg-base p-[var(--ui-gap)]">
      <form
        onSubmit={submit}
        className="flex w-full max-w-sm flex-col gap-[var(--ui-gap)] rounded-panel border border-border bg-panel p-4"
      >
        <div className="flex items-center gap-2 text-primary">
          <KeyRound className="h-[var(--ui-icon)] w-[var(--ui-icon)]" />
          <h1 className="text-[length:var(--ui-text-title)]">Token required</h1>
        </div>
        <p className="text-[length:var(--ui-text-body)] text-muted">
          This server was started with <code className="font-mono text-faint">--token</code>. Paste
          it below, or open the one-time URL <code className="font-mono text-faint">/?t=&lt;token&gt;</code>{' '}
          that <code className="font-mono text-faint">alc ui</code> printed.
        </p>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label="API token"
          autoComplete="off"
          className="h-[var(--ui-control-h)] min-h-[var(--ui-control-h)] rounded-panel border border-border bg-base px-2 font-mono text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
        />
        <button
          type="submit"
          className="h-[var(--ui-control-h)] min-h-[var(--ui-control-h)] rounded-panel border border-border bg-raised text-[length:var(--ui-text-body)] text-primary hover:bg-hover"
        >
          Connect
        </button>
      </form>
    </div>
  )
}
