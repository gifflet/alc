// RunDetail.tsx — One run: Assurance Loop timeline + event feed + scorecard.
//
// Loads the run's events, then tails live: WS run_event messages for this stem
// carry each new JSONL line, appended in place so an active run animates without
// any refresh. buildTimeline turns the raw events into the segmented track.
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Radio } from 'lucide-react'
import { api, artifactFileUrl } from '../api/client'
import { keys } from '../api/keys'
import { useRunArtifacts } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useWs } from '../ws/WsProvider'
import { buildTimeline, describeEvent } from '../lib/runEvents'
import type { RunEvent } from '../api/types'
import { TimelineView } from '../components/Timeline'
import { Metric, Pill } from '../components/primitives'
import { StatusDot } from '../components/StatusDot'
import { EmptyState } from '../components/EmptyState'

export function RunDetail({ stem }: { stem: string }) {
  const id = useProjectId()
  const { client } = useWs()
  const [events, setEvents] = useState<RunEvent[]>([])
  // A live WS event proves a process is still writing this run — clears stale.
  const [live, setLive] = useState(false)

  const query = useQuery({
    queryKey: keys.run(id, stem),
    queryFn: () => api.getRun(id, stem),
  })
  const artifacts = useRunArtifacts(id, stem)
  const evidence = artifacts.data?.artifacts ?? []

  // Seed local events from the fetched snapshot.
  useEffect(() => {
    if (query.data) setEvents(query.data.events)
  }, [query.data])

  // Live tail: append each new line pushed for this run.
  useEffect(() => {
    const off = client.on((msg) => {
      if (msg.type === 'run_event' && msg.project_id === id && msg.stem === stem) {
        setEvents((prev) => [...prev, msg.event])
        setLive(true)
      }
    })
    return off
  }, [client, id, stem])

  if (query.isError) {
    return <EmptyState icon={Radio} message={`Could not load run ${stem}.`} />
  }

  const timeline = buildTimeline(events)
  // Unfinished + backend flagged stale + no live event since mount = interrupted.
  const isStale = !timeline.finished && (query.data?.stale ?? false) && !live
  const statusTone =
    timeline.success === true ? 'live' : timeline.success === false ? 'error' : 'running'

  return (
    <div className="flex h-full flex-col overflow-auto p-4">
      <header className="mb-3 flex items-center gap-3">
        <StatusDot tone={isStale ? 'warn' : statusTone} pulse={!timeline.finished && !isStale} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-[14px] font-medium text-primary">{timeline.title || stem}</h1>
            {timeline.finished ? (
              <Pill tone={statusTone}>{timeline.success ? 'success' : 'failed'}</Pill>
            ) : isStale ? (
              <Pill tone="warn">stale</Pill>
            ) : (
              <Pill tone="running">live</Pill>
            )}
          </div>
          <p className="truncate text-[12px] text-muted">{timeline.task}</p>
        </div>
        {timeline.engine && (
          <span className="ml-auto font-mono text-[11px] text-faint">
            {timeline.engine}
            {timeline.model ? `/${timeline.model}` : ''}
          </span>
        )}
      </header>

      {events.length === 0 ? (
        <EmptyState icon={Radio} message="No events yet." />
      ) : (
        <>
          {timeline.checkConfigEdits.length > 0 && (
            <div className="mb-4 rounded-panel border border-warn/40 bg-warn/10 px-3 py-2 text-warn">
              <p className="text-[12px] font-medium">
                ⚠ This run modified check-defining config — review before trusting the result:
              </p>
              <ul className="mt-1 font-mono text-[11px]">
                {timeline.checkConfigEdits.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </div>
          )}

          <TimelineView timeline={timeline} />

          {timeline.scorecard && (
            <div className="mt-4 flex gap-6 rounded-panel border border-border bg-panel px-4 py-3">
              <Metric label="span" value={timeline.scorecard.span} tone="live" />
              <Metric label="passes" value={timeline.scorecard.passes} />
              <Metric label="streak" value={timeline.scorecard.streak} />
              <Metric label="touch" value={timeline.scorecard.touch} />
              {timeline.commitSha && (
                <div className="ml-auto flex items-center font-mono text-[11px] text-faint">
                  commit {timeline.commitSha.slice(0, 10)}
                </div>
              )}
            </div>
          )}

          {evidence.length > 0 && (
            <section className="mt-4">
              <h2 className="mb-1 text-[11px] uppercase tracking-wide text-faint">Evidence</h2>
              <ul className="rounded-panel border border-border bg-base text-[12px]">
                {evidence.map((a) => (
                  <li
                    key={a.path}
                    className="flex items-center gap-3 border-b border-border/50 px-3 py-1.5 last:border-b-0"
                  >
                    <span className="w-12 shrink-0 font-mono text-[10px] uppercase tracking-wide text-faint">
                      {a.type}
                    </span>
                    <a
                      href={artifactFileUrl(id, a.path)}
                      target="_blank"
                      rel="noreferrer"
                      className="min-w-0 flex-1 truncate font-mono text-[11px] text-accent hover:underline"
                    >
                      {a.path}
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="mt-4">
            <h2 className="mb-1 text-[11px] uppercase tracking-wide text-faint">Events</h2>
            <ul className="rounded-panel border border-border bg-base font-mono text-[11px]">
              {events.map((e, i) => (
                <li
                  key={i}
                  className="flex items-baseline gap-3 border-b border-border/50 px-3 py-1 last:border-b-0"
                >
                  <span className="shrink-0 text-faint">{String(e.ts).slice(11, 19)}</span>
                  <span className="text-muted">{describeEvent(e)}</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
