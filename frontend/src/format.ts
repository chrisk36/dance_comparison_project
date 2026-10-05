/** 4.23 -> "0:04.2" */
export function formatTime(t: number): string {
  const m = Math.floor(t / 60)
  const s = t - m * 60
  return `${m}:${s.toFixed(1).padStart(4, '0')}`
}

/** "left_arm" -> "left arm" */
export function formatPart(part: string): string {
  return part.replace('_', ' ')
}
