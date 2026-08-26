'use client'

import { useEffect, useRef, useState } from 'react'
import { Play } from 'lucide-react'

// Demo.tsx — A looping product recording.
//
// Not a GIF. The same 9 seconds as a GIF runs past 5 MB and is capped at 256
// colours, which destroys the one thing the recording exists to show: the
// status colours of the loop and the syntax highlighting. As MP4 it is 66 KB,
// in real colour.
//
// Autoplay is conditional, and that condition is the whole design. A reader who
// set `prefers-reduced-motion` asked the system for less movement; a landing
// page that starts playing anyway is overriding an accessibility preference for
// decoration. Those readers get the poster and a play button, which is the same
// content without the motion.

type Props = {
  src: string
  poster: string
  /** Intrinsic size — reserves the box so the page never reflows on load. */
  width: number
  height: number
  caption?: string
  /** Label announced to assistive tech; the video has no audio track. */
  label: string
  className?: string
}

export function Demo({ src, poster, width, height, caption, label, className = '' }: Props) {
  const ref = useRef<HTMLVideoElement>(null)
  const [reduced, setReduced] = useState(false)
  const [manual, setManual] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const apply = () => setReduced(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  // Play only while on screen. A video looping in a section the reader scrolled
  // past is decoding frames nobody is watching, which costs battery on a phone
  // for no benefit.
  useEffect(() => {
    const el = ref.current
    if (!el || reduced) return
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) el.play().catch(() => {})
        else el.pause()
      },
      { threshold: 0.25 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [reduced])

  const autoplay = !reduced || manual

  return (
    <figure className={`m-0 ${className}`}>
      <div className="relative overflow-hidden rounded-lg border border-border bg-panel shadow-[var(--elev-2)]">
        <video
          ref={ref}
          className="block h-auto w-full"
          src={src}
          poster={poster}
          width={width}
          height={height}
          muted
          loop
          playsInline
          autoPlay={autoplay}
          preload={reduced ? 'none' : 'metadata'}
          controls={reduced && manual}
          aria-label={label}
        />
        {reduced && !manual && (
          <button
            type="button"
            onClick={() => {
              setManual(true)
              requestAnimationFrame(() => ref.current?.play().catch(() => {}))
            }}
            className="absolute inset-0 grid place-items-center bg-black/35 transition-colors hover:bg-black/25"
          >
            <span className="flex min-h-[44px] items-center gap-2.5 rounded-md bg-base/90 px-5 text-sm font-medium text-primary shadow-[var(--elev-2)]">
              <Play size={15} />
              Play demo
            </span>
          </button>
        )}
      </div>
      {caption && (
        <figcaption className="mt-3.5 text-sm leading-relaxed text-faint">{caption}</figcaption>
      )}
    </figure>
  )
}
