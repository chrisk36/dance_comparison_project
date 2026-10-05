import { useCallback, useEffect, useRef, useState } from 'react'

/** Drift (s) above which the comparison is hard-seeked back to the reference. */
const SEEK_DRIFT = 0.25
/** Drift (s) above which the comparison's playback rate is nudged to catch up. */
const NUDGE_DRIFT = 0.02

/**
 * Plays two frame-locked clips together. The reference video is the master clock; the
 * comparison follows it (same currentTime, since both clips are trimmed to the overlap).
 */
export function useSyncedVideos(fps: number) {
  const refVideo = useRef<HTMLVideoElement>(null)
  const compVideo = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  const [frame, setFrame] = useState(0)
  const [duration, setDuration] = useState(0)

  // Animation loop: follow the master clock, correct drift, publish the current frame.
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const r = refVideo.current
      const c = compVideo.current
      if (r && c) {
        if (!r.paused) {
          // Small drift: speed the comparison up/down slightly (seeking mid-playback stalls
          // decoding). Large drift (e.g. after buffering): seek.
          const drift = c.currentTime - r.currentTime
          if (Math.abs(drift) > SEEK_DRIFT) c.currentTime = r.currentTime
          else if (Math.abs(drift) > NUDGE_DRIFT) c.playbackRate = Math.min(1.1, Math.max(0.9, 1 - drift * 2))
          else if (c.playbackRate !== 1) c.playbackRate = 1
        }
        setFrame(Math.floor(r.currentTime * fps + 1e-6))
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [fps])

  const play = useCallback(async () => {
    const r = refVideo.current
    const c = compVideo.current
    if (!r || !c) return
    if (r.ended) r.currentTime = 0
    c.currentTime = r.currentTime
    await Promise.all([r.play(), c.play()]).catch(() => undefined)
    setPlaying(true)
  }, [])

  const pause = useCallback(() => {
    const r = refVideo.current
    const c = compVideo.current
    r?.pause()
    c?.pause()
    if (r && c) {
      c.currentTime = r.currentTime
      c.playbackRate = 1
    }
    setPlaying(false)
  }, [])

  const seek = useCallback((t: number) => {
    const r = refVideo.current
    const c = compVideo.current
    if (!r || !c) return
    const clamped = Math.max(0, Math.min(t, (r.duration || t) - 0.01))
    r.currentTime = clamped
    c.currentTime = clamped
    setFrame(Math.floor(clamped * fps + 1e-6))
  }, [fps])

  // Wire up master-clock events once the elements exist.
  useEffect(() => {
    const r = refVideo.current
    const c = compVideo.current
    if (!r || !c) return
    const onMeta = () => setDuration(r.duration || 0)
    const onEnded = () => {
      c.pause()
      setPlaying(false)
    }
    r.addEventListener('loadedmetadata', onMeta)
    r.addEventListener('ended', onEnded)
    if (r.readyState >= 1) onMeta()
    return () => {
      r.removeEventListener('loadedmetadata', onMeta)
      r.removeEventListener('ended', onEnded)
    }
  }, [])

  return { refVideo, compVideo, playing, play, pause, seek, frame, time: frame / fps, duration }
}
