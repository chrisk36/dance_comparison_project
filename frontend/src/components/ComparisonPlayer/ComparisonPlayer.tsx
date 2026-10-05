import { useEffect, useMemo, useState } from 'react'
import type { Results, Segment } from '../../types'
import { LEVEL_COLOR, LEVEL_LABEL } from '../../syncColor'
import { buildSyncTrack } from './syncTrack'
import SegmentList from './SegmentList'
import Timeline from './Timeline'
import { useSyncedVideos } from './useSyncedVideos'

interface Props {
  results: Results
  referenceUrl: string
  comparisonUrl: string
}

/** The two trimmed clips side by side, with a live in-sync colour and the flagged moments. */
export default function ComparisonPlayer({ results, referenceUrl, comparisonUrl }: Props) {
  const { refVideo, compVideo, playing, play, pause, seek, frame, time, duration } = useSyncedVideos(results.fps)
  const track = useMemo(() => buildSyncTrack(results), [results])
  const [mirrorComp, setMirrorComp] = useState(results.mirrored.global)
  const [audio, setAudio] = useState<'reference' | 'comparison'>('reference')

  const level = track[Math.min(frame, track.length - 1)] ?? 'none'
  const color = LEVEL_COLOR[level]
  const activeSegment = results.segments.findIndex((s) => time >= s.start && time < s.end)

  // Space toggles play/pause.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || (e.target as HTMLElement).tagName === 'INPUT') return
      e.preventDefault()
      if (playing) pause()
      else play()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [playing, play, pause])

  function selectSegment(s: Segment) {
    seek(s.start)
  }

  const videoBox = 'relative overflow-hidden rounded-xl bg-black transition-shadow duration-150'
  const glow = { boxShadow: `0 0 0 4px ${color}, 0 0 28px 2px ${color}66` }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center gap-4">
        <div>
          <div className="text-xs uppercase tracking-wide text-zinc-500">Overall</div>
          <div className="text-4xl font-semibold tabular-nums">
            {results.overall_score === null ? '—' : Math.round(results.overall_score)}
            <span className="text-lg text-zinc-500">/100</span>
          </div>
        </div>
        <div
          className="rounded-full px-3 py-1 text-sm font-medium text-zinc-950 transition-colors"
          style={{ backgroundColor: color }}
        >
          {LEVEL_LABEL[level]}
        </div>
        {results.mirrored.global && (
          <div className="rounded-full bg-zinc-800 px-3 py-1 text-sm text-zinc-300">Mirrored dance detected</div>
        )}
        <div className="ml-auto text-right text-xs text-zinc-500">
          {results.segments.length} out-of-sync moment{results.segments.length === 1 ? '' : 's'}
          <br />
          audio offset {results.alignment.offset_seconds.toFixed(2)}s
        </div>
      </header>

      <div className="grid grid-cols-2 gap-4">
        <figure className="space-y-2">
          <div className={videoBox} style={glow}>
            <video ref={refVideo} src={referenceUrl} muted={audio !== 'reference'} playsInline preload="auto"
              className="h-[62vh] w-full object-contain" />
          </div>
          <figcaption className="text-sm text-zinc-400">Reference</figcaption>
        </figure>
        <figure className="space-y-2">
          <div className={videoBox} style={glow}>
            <video ref={compVideo} src={comparisonUrl} muted={audio !== 'comparison'} playsInline preload="auto"
              className="h-[62vh] w-full object-contain" style={mirrorComp ? { transform: 'scaleX(-1)' } : undefined} />
          </div>
          <figcaption className="text-sm text-zinc-400">Comparison</figcaption>
        </figure>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button onClick={playing ? pause : play}
          className="w-24 rounded-lg bg-zinc-100 px-4 py-2 font-medium text-zinc-900">
          {playing ? 'Pause' : 'Play'}
        </button>
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          Sound
          <select value={audio} onChange={(e) => setAudio(e.target.value as typeof audio)}
            className="rounded-md bg-zinc-800 px-2 py-1">
            <option value="reference">Reference</option>
            <option value="comparison">Comparison</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input type="checkbox" checked={mirrorComp} onChange={(e) => setMirrorComp(e.target.checked)} />
          Mirror comparison
        </label>
      </div>

      <Timeline track={track} fps={results.fps} duration={duration} time={time}
        segments={results.segments} onSeek={seek} />

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-zinc-300">Out-of-sync moments</h2>
        <SegmentList segments={results.segments} activeIndex={activeSegment} onSelect={selectSegment} />
      </section>
    </div>
  )
}
