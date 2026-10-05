# Interface contract

This file is the single source of truth for how the three parts plug together:
- alignment (Wei)
- pose/scoring (Christian)
- UI (all three, styled by Nat)

The Python models in `dancecv/contract.py` implement it, and `frontend/src/types.ts` mirrors it. Change all three together.

```
upload (Wei) ──► align(ref, comp, out_dir) ──► alignment.json (+ trimmed clips)
                                                    │
                                                    ▼
                       run_from_alignment(alignment.json, out_dir) ──► results.json
                                                                             │
                                                                             ▼
                                                     UI: ComparisonPlayer(results)
```

## 1. Alignment step

### Python entry point
```python
# dancecv/alignment/audio.py  (Wei — real implementation)
# dancecv/alignment/stub.py   (Christian — dev stand-in, same signature)
def align(ref_path, comp_path, out_dir, trim: bool = True) -> dancecv.contract.Alignment:
    """Writes <out_dir>/alignment.json (and trimmed clips when trim=True) and returns it."""
```

### `alignment.json`
```jsonc
{
  "reference_video": "ref.mp4",          // absolute, or relative to this json's directory
  "comparison_video": "comp.mp4",
  "offset_seconds": 0.9355,              // comparison_time = reference_time + offset_seconds
  "overlap_start_ref": 0.0,              // reference-time seconds where both videos have content
  "overlap_end_ref": 21.5249,
  "reference_fps": 30.0,
  "comparison_fps": 30.0,
  "alignment_confidence": 0.71,          // 0–1

  // OPTIONAL. If present: both clips are cut to [overlap_start_ref, overlap_end_ref]
  // (comparison cut at the same span shifted by offset), re-encoded at constant 30 fps,
  // H.264/yuv420p, so frame N of one == frame N of the other.
  "reference_trimmed": "ref_trimmed.mp4",
  "comparison_trimmed": "comp_trimmed.mp4"
}
```

Rules:
- The alignment step **only** aligns timing: no zoom, crop, aspect-ratio or mirroring changes.
- Extra keys are allowed and ignored, so feel free to add debug fields.
- If the trimmed clips are missing, the scoring step makes them itself from the originals plus the offset. The UI therefore always plays trimmed clips.

## 2. Scoring step

### Python entry point
```python
# dancecv/pipeline.py
def run_from_alignment(alignment_path, out_dir) -> dancecv.contract.Results:
    """Writes <out_dir>/results.json (+ debug artifacts) and returns it."""
```

### `results.json`
**All primary times are trimmed-clip seconds:** 0 = overlap start, which is what the player shows. Times in the original videos are given as `*_ref_orig` / `*_comp_orig`.

```jsonc
{
  "schema_version": 1,
  "alignment": { /* echo of alignment.json, paths resolved */ },
  "media": {
    "reference_trimmed": "…/ref_trimmed.mp4",
    "comparison_trimmed": "…/comp_trimmed.mp4",
    "debug_video": "…/debug.mp4"          // optional
  },
  "fps": 30.0,
  "overall_score": 81.3,                  // 0–100, null if nothing could be scored
  "mirrored": {
    "global": false,                      // comparison dancer mirrors the reference
    "segments": [{ "start": 0.0, "end": 21.5, "mirrored": false }]
  },
  "segments": [                           // out-of-sync stretches
    {
      "start": 4.2, "end": 5.8,
      "start_ref_orig": 4.2, "end_ref_orig": 5.8,
      "start_comp_orig": 5.14, "end_comp_orig": 6.74,
      "severity": 0.42,                   // 0–1, higher = worse
      "severity_label": "medium",         // low | medium | high
      "mean_score": 52.1,
      "worst_body_parts": ["left_arm", "right_leg"]
    }
  ],
  "no_pose_segments": [{ "start": 17.5, "end": 21.5 }],   // no dancer found (e.g. end cards); not scored
  "frames": {                             // one entry per trimmed-clip frame
    "t": [0.0, 0.0333, …],
    "score": [97.1, 96.4, null, …],       // 0–100, null = no valid pose
    "lag_frames": [0, 1, null, …],        // best comp lag in the tolerance window (+ = comp late)
    "mirrored": [false, …],
    "part_scores": { "left_arm": […], "right_arm": […], "left_leg": […], "right_leg": […], "torso": […], "head": […] },
    "limb_angle_err_deg": { "l_upper_arm": […], … }
  },
  "params": { "flag_threshold": 60, … }   // thresholds used, for reproducibility
}
```

Body parts: `left_arm`, `right_arm`, `left_leg`, `right_leg`, `torso`, `head`. These are the *reference dancer's* left and right.

## 3. HTTP API (FastAPI, `server/app.py`)
| Method | Path | Body / returns |
|---|---|---|
| POST | `/api/jobs` | multipart `reference`, `comparison` files → `{ "job_id": "…" }` |
| POST | `/api/jobs/from-alignment` | JSON `{ "alignment_path": "…" }` (server-local) → `{ "job_id": "…" }` |
| GET | `/api/jobs/{id}` | `{ "status": "queued\|aligning\|pose\|scoring\|done\|error", "progress": 0–1, "error": null }` |
| GET | `/api/jobs/{id}/results` | `results.json` |
| GET | `/api/jobs/{id}/media/{reference\|comparison\|debug}` | video file (range requests supported) |

## 4. Frontend components (`frontend/src/`)
| File | Owner | Contract |
|---|---|---|
| `types.ts`, `api.ts` | shared | mirror sections 2 and 3 |
| `components/UploadPanel.tsx` | Wei (placeholder by Christian) | `props: { onJobCreated(jobId: string): void }`. Call it after `POST /api/jobs` returns. |
| `components/ComparisonPlayer/*` | Christian | `props: { results: Results; referenceUrl: string; comparisonUrl: string }`. Plays the trimmed clips frame-locked. |
| `syncColor.ts` | Nat (palette) | `scoreToLevel(score, flagThreshold) → 'good' \| 'ok' \| 'bad' \| 'none'`, `LEVEL_COLOR`, `LEVEL_LABEL` |
| `App.tsx` | shared | upload → poll `GET /api/jobs/{id}` → `ComparisonPlayer`. Job id kept in `?job=` |

Live colour rule:
- **red** only inside a flagged segment
- otherwise **green** if the 0.2 s-smoothed score is ≥ 80, **amber** below that
- **grey** where no dancer was found

This keeps the colours consistent with the segment list.
