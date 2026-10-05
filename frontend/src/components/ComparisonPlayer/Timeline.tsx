import { useEffect, useRef } from 'react'
import type { Segment } from '../../types'
import { LEVEL_COLOR, type SyncLevel } from '../../syncColor'
import { formatTime } from '../../format'

interface Props {
  track: SyncLevel[]
  fps: number
  duration: number
  time: number
  segments: Segment[]
  onSeek(t: number): void
}

/** Colour strip of per-frame sync, flagged segments outlined, click anywhere to seek. */
export default function Timeline({ track, fps, duration, time, segments, onSeek }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const total = duration || track.length / fps

  useEffect(() => {
    const el = canvas.current
    if (!el) return
    const draw = () => {
      const dpr = window.devicePixelRatio || 1
      const w = el.clientWidth
      const h = el.clientHeight
      el.width = Math.round(w * dpr)
      el.height = Math.round(h * dpr)
      const ctx = el.getContext('2d')!
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, w, h)
      const fw = w / (total * fps)
      track.forEach((level, i) => {
        ctx.fillStyle = LEVEL_COLOR[level]
        ctx.fillRect(i * fw, 0, fw + 0.5, h)
      })
    }
    draw()
    const ro = new ResizeObserver(draw)
    ro.observe(el)
    return () => ro.disconnect()
  }, [track, fps, total])

  function handleClick(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    onSeek(((e.clientX - rect.left) / rect.width) * total)
  }

  const pct = (t: number) => `${(100 * t) / total}%`

  return (
    <div className="space-y-1">
      <div className="relative h-8 cursor-pointer overflow-hidden rounded-md" onClick={handleClick}>
        <canvas ref={canvas} className="absolute inset-0 h-full w-full" />
        {segments.map((s) => (
          <div
            key={s.start}
            title={`${formatTime(s.start)}–${formatTime(s.end)}`}
            className="pointer-events-none absolute inset-y-0 border-2 border-white/80"
            style={{ left: pct(s.start), width: pct(s.end - s.start) }}
          />
        ))}
        <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white" style={{ left: pct(time) }} />
      </div>
      <div className="flex justify-between text-xs tabular-nums text-zinc-500">
        <span>{formatTime(time)}</span>
        <span>{formatTime(total)}</span>
      </div>
    </div>
  )
}
