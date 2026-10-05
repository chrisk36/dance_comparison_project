import type { Results } from '../../types'
import { scoreToLevel, type SyncLevel } from '../../syncColor'

/**
 * Per-frame sync level for display. Uses the same 0.2 s smoothing as the backend so the
 * colours agree with the flagged segments: red only inside a flagged segment, otherwise
 * green/amber from the smoothed score, grey where no dancer was found.
 */
export function buildSyncTrack(results: Results): SyncLevel[] {
  const { score } = results.frames
  const fps = results.fps
  const threshold = results.params.flag_threshold
  const win = Math.max(1, Math.round(((results.params.smooth_s as number) ?? 0.2) * fps))
  const half = Math.floor(win / 2)

  const flagged = new Array<boolean>(score.length).fill(false)
  for (const s of results.segments) {
    const a = Math.round(s.start * fps)
    const b = Math.min(score.length, Math.round(s.end * fps))
    for (let i = a; i < b; i++) flagged[i] = true
  }

  return score.map((v, i) => {
    if (v === null) return 'none'
    if (flagged[i]) return 'bad'
    let sum = 0
    let n = 0
    for (let j = Math.max(0, i - half); j <= Math.min(score.length - 1, i + half); j++) {
      const x = score[j]
      if (x !== null) {
        sum += x
        n++
      }
    }
    const level = scoreToLevel(sum / n, threshold)
    return level === 'bad' ? 'ok' : level // brief dips that were not flagged stay amber
  })
}
