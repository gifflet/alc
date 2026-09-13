// EvidenceGallery.tsx — inline preview of a run's captured e2e evidence.
//
// Two shapes, split by artifact type: images (screenshots) go into a carousel;
// everything else (a backend's JSON/text response, an HTML page's source, a
// health-poll log) renders as text. Bytes are fetched WITH the bearer token
// (api.artifactText / api.artifactObjectUrl) — a bare <img src>/<a href> can't
// carry the header, so on a token-protected server it would 401.
import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, FileText, ImageOff } from 'lucide-react'
import { api, artifactFileUrl } from '../api/client'
import type { Artifact } from '../api/types'

// A generous cap so a 100KB+ HTML dump can't freeze the panel. The full file
// stays one click away via the download link.
const MAX_PREVIEW_CHARS = 100_000

function prettyIfJson(text: string): string {
  const trimmed = text.trimStart()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return text
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text // not valid JSON after all — show it verbatim
  }
}

/** One non-image artifact rendered as text: a backend response, HTML source,
 * or a log. Fetches on mount; shows loading / error / (possibly truncated)
 * content. */
function TextEvidence({ id, artifact }: { id: string; artifact: Artifact }) {
  const [state, setState] = useState<{ text: string; error: string | null; loading: boolean }>({
    text: '',
    error: null,
    loading: true,
  })

  useEffect(() => {
    let live = true
    api
      .artifactText(id, artifact.path)
      .then((raw) => {
        if (live) setState({ text: prettyIfJson(raw), error: null, loading: false })
      })
      .catch((e: unknown) => {
        if (live) setState({ text: '', error: e instanceof Error ? e.message : 'failed to load', loading: false })
      })
    return () => {
      live = false
    }
  }, [id, artifact.path])

  const truncated = state.text.length > MAX_PREVIEW_CHARS
  const shown = truncated ? state.text.slice(0, MAX_PREVIEW_CHARS) : state.text

  return (
    <figure className="m-0 overflow-hidden rounded-panel border border-border bg-base">
      <figcaption className="flex items-center gap-2 border-b border-border/50 px-3 py-1.5">
        <FileText className="h-3.5 w-3.5 shrink-0 text-faint" />
        <span className="min-w-0 flex-1 truncate font-mono text-[length:var(--ui-text-label)] text-muted">
          {artifact.path.split('/').pop()}
        </span>
        <span className="shrink-0 font-mono text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
          {artifact.type}
        </span>
        <a
          href={artifactFileUrl(id, artifact.path)}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 text-[length:var(--ui-text-label)] text-accent hover:underline"
        >
          open
        </a>
      </figcaption>
      {state.loading ? (
        <p className="px-3 py-2 text-[length:var(--ui-text-body)] text-faint">Loading…</p>
      ) : state.error ? (
        <p className="px-3 py-2 text-[length:var(--ui-text-body)] text-error">Could not load: {state.error}</p>
      ) : (
        <>
          <pre className="max-h-96 overflow-auto px-3 py-2 text-[length:var(--ui-text-label)] leading-relaxed text-primary [overflow-wrap:anywhere] whitespace-pre-wrap">
            {shown}
          </pre>
          {truncated && (
            <p className="border-t border-border/50 px-3 py-1.5 text-[length:var(--ui-text-label)] text-faint">
              Preview truncated at {MAX_PREVIEW_CHARS.toLocaleString()} chars — use “open” for the full file.
            </p>
          )}
        </>
      )}
    </figure>
  )
}

/** Every image artifact in one carousel: the current image large, arrows and a
 * counter when there is more than one. Object URLs are fetched lazily and
 * revoked on unmount. */
function ImageCarousel({ id, images }: { id: string; images: Artifact[] }) {
  const [idx, setIdx] = useState(0)
  const [urls, setUrls] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const current = images[idx]

  useEffect(() => {
    let live = true
    if (current && urls[current.path] === undefined) {
      api
        .artifactObjectUrl(id, current.path)
        .then((u) => {
          if (live) setUrls((prev) => ({ ...prev, [current.path]: u }))
          else URL.revokeObjectURL(u)
        })
        .catch((e: unknown) => {
          if (live) setError(e instanceof Error ? e.message : 'failed to load')
        })
    }
    return () => {
      live = false
    }
  }, [id, current, urls])

  // Revoke every object URL when the carousel unmounts.
  useEffect(() => {
    return () => {
      Object.values(urls).forEach((u) => URL.revokeObjectURL(u))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!current) return null
  const url = urls[current.path]
  const go = (delta: number) => setIdx((i) => (i + delta + images.length) % images.length)

  return (
    <figure className="m-0 overflow-hidden rounded-panel border border-border bg-base">
      <figcaption className="flex items-center gap-2 border-b border-border/50 px-3 py-1.5">
        <span className="min-w-0 flex-1 truncate font-mono text-[length:var(--ui-text-label)] text-muted">
          {current.path.split('/').pop()}
        </span>
        {images.length > 1 && (
          <span className="shrink-0 font-mono text-[length:var(--ui-text-label)] tabular-nums text-faint">
            {idx + 1}/{images.length}
          </span>
        )}
        <a
          href={artifactFileUrl(id, current.path)}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 text-[length:var(--ui-text-label)] text-accent hover:underline"
        >
          open
        </a>
      </figcaption>
      <div className="relative flex items-center justify-center bg-panel">
        {error ? (
          <p className="flex items-center gap-2 px-3 py-8 text-[length:var(--ui-text-body)] text-error">
            <ImageOff className="h-4 w-4" /> Could not load: {error}
          </p>
        ) : url ? (
          <img src={url} alt={current.path} className="max-h-[28rem] w-full object-contain" />
        ) : (
          <p className="px-3 py-8 text-[length:var(--ui-text-body)] text-faint">Loading…</p>
        )}
        {images.length > 1 && (
          <>
            <button
              type="button"
              aria-label="Previous screenshot"
              onClick={() => go(-1)}
              className="absolute left-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-border bg-base/80 text-muted hover:text-primary"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label="Next screenshot"
              onClick={() => go(1)}
              className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-border bg-base/80 text-muted hover:text-primary"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </>
        )}
      </div>
    </figure>
  )
}

export function EvidenceGallery({
  id,
  artifacts,
  serviceRun = false,
}: {
  id: string
  artifacts: Artifact[]
  /** True when this run started a service (a needs_service e2e). A service run
   * with no screenshot means the visual check never happened — worth saying. */
  serviceRun?: boolean
}) {
  const images = artifacts.filter((a) => a.type === 'image')
  const docs = artifacts.filter((a) => a.type !== 'image')
  return (
    <div className="flex flex-col gap-3">
      {serviceRun && images.length === 0 && (
        <div className="rounded-panel border border-warn/40 bg-warn/10 px-3 py-2 text-warn">
          <p className="text-[length:var(--ui-text-body)] font-medium">
            No screenshot — the e2e did not visually verify a screen.
          </p>
          <p className="mt-1 text-[length:var(--ui-text-label)] text-muted">
            The run exercised the service but captured no image, so nothing here proves how the
            screen looks. To verify a UI change, set the blueprint&rsquo;s{' '}
            <span className="font-mono">capture:</span> to a screenshot of the affected route — e.g.{' '}
            <span className="font-mono [overflow-wrap:anywhere]">
              playwright screenshot &quot;$ALC_BASE_URL/&lt;route&gt;&quot; &quot;$ALC_ARTIFACTS_DIR/screen.png&quot;
            </span>{' '}
            — or have the e2e capture the screen it changed.
          </p>
        </div>
      )}
      {images.length > 0 && <ImageCarousel id={id} images={images} />}
      {docs.map((a) => (
        <TextEvidence key={a.path} id={id} artifact={a} />
      ))}
    </div>
  )
}
