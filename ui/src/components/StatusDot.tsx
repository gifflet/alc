// StatusDot.tsx — A small status indicator dot with an optional live pulse.
export type Tone = 'live' | 'running' | 'error' | 'warn' | 'idle' | 'accent'

const TONE_BG: Record<Tone, string> = {
  live: 'bg-live',
  running: 'bg-running',
  error: 'bg-error',
  warn: 'bg-warn',
  idle: 'bg-faint',
  accent: 'bg-accent',
}

export function StatusDot({
  tone,
  pulse = false,
  title,
}: {
  tone: Tone
  pulse?: boolean
  title?: string
}) {
  return (
    <span
      title={title}
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${TONE_BG[tone]} ${
        pulse ? 'alc-pulse' : ''
      }`}
    />
  )
}
