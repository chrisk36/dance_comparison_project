import type { Segment } from '../../types'
import { formatPart, formatTime } from '../../format'

interface Props {
  segments: Segment[]
  activeIndex: number
  onSelect(s: Segment): void
}

const SEVERITY_STYLE: Record<Segment['severity_label'], string> = {
  low: 'bg-amber-500/15 text-amber-300',
  medium: 'bg-orange-500/15 text-orange-300',
  high: 'bg-red-500/15 text-red-300',
}

export default function SegmentList({ segments, activeIndex, onSelect }: Props) {
  if (segments.length === 0) {
    return <p className="text-sm text-zinc-400">No out-of-sync moments found.</p>
  }
  return (
    <ul className="space-y-1.5">
      {segments.map((s, i) => (
        <li key={s.start}>
          <button
            onClick={() => onSelect(s)}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
              i === activeIndex ? 'bg-zinc-700' : 'bg-zinc-900 hover:bg-zinc-800'
            }`}
          >
            <span className="font-medium tabular-nums">
              {formatTime(s.start)}–{formatTime(s.end)}
            </span>
            <span className={`rounded px-1.5 py-0.5 text-xs ${SEVERITY_STYLE[s.severity_label]}`}>
              {s.severity_label}
            </span>
            <span className="truncate text-zinc-400">{s.worst_body_parts.map(formatPart).join(', ')}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
