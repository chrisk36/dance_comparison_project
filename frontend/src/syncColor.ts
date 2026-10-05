// Score -> colour mapping. One place for the palette so it can be restyled freely.

export type SyncLevel = 'good' | 'ok' | 'bad' | 'none'

/** Scores at or above this are "good"; between the flag threshold and this are "ok". */
export const GOOD_SCORE = 80

export const LEVEL_COLOR: Record<SyncLevel, string> = {
  good: '#22c55e', // green-500
  ok: '#f59e0b', // amber-500
  bad: '#ef4444', // red-500
  none: '#52525b', // zinc-600
}

export const LEVEL_LABEL: Record<SyncLevel, string> = {
  good: 'In sync',
  ok: 'Close',
  bad: 'Out of sync',
  none: 'No dancer',
}

export function scoreToLevel(score: number | null, flagThreshold = 60): SyncLevel {
  if (score === null || Number.isNaN(score)) return 'none'
  if (score >= GOOD_SCORE) return 'good'
  if (score >= flagThreshold) return 'ok'
  return 'bad'
}

export function scoreToColor(score: number | null, flagThreshold = 60): string {
  return LEVEL_COLOR[scoreToLevel(score, flagThreshold)]
}
