// Mirrors dancecv/contract.py and CONTRACT.md. Change all three together.

export type BodyPart = 'left_arm' | 'right_arm' | 'left_leg' | 'right_leg' | 'torso' | 'head'

export interface Alignment {
  reference_video: string
  comparison_video: string
  offset_seconds: number
  overlap_start_ref: number
  overlap_end_ref: number
  reference_fps: number
  comparison_fps: number
  alignment_confidence: number
  reference_trimmed?: string
  comparison_trimmed?: string
}

/** All primary times are trimmed-clip seconds (0 = overlap start). */
export interface Segment {
  start: number
  end: number
  start_ref_orig: number
  end_ref_orig: number
  start_comp_orig: number
  end_comp_orig: number
  severity: number
  severity_label: 'low' | 'medium' | 'high'
  mean_score: number
  worst_body_parts: BodyPart[]
}

export interface Span {
  start: number
  end: number
}

export interface Results {
  schema_version: number
  alignment: Alignment
  media: { reference_trimmed: string; comparison_trimmed: string; debug_video?: string | null }
  fps: number
  overall_score: number | null
  mirrored: { global: boolean; segments: (Span & { mirrored: boolean })[] }
  segments: Segment[]
  no_pose_segments: Span[]
  frames: {
    t: number[]
    score: (number | null)[]
    lag_frames: (number | null)[]
    mirrored: boolean[]
    part_scores: Record<BodyPart, (number | null)[]>
    limb_angle_err_deg: Record<string, (number | null)[]>
  }
  params: Record<string, unknown> & { flag_threshold: number }
}

export type JobState = 'queued' | 'aligning' | 'pose' | 'scoring' | 'done' | 'error'

export interface JobStatus {
  job_id: string
  status: JobState
  progress: number
  error: string | null
}
