# Backend v3 — music matching with playback-speed correction

## Install

Stop FastAPI with Ctrl+C. Copy `backend/app/alignment.py` from this archive over the same file in your existing project. Other backend runtime files are included unchanged. Keep your data folder and existing frontend.

From the existing project root:

```bash
source .venv/bin/activate
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

No Docker or new dependencies are needed. If setting up from scratch, install `backend/requirements.txt` in your virtual environment and install FFmpeg/ffprobe.

## Actual uploaded-video diagnosis

The music is shared, but the source audio timing differs by approximately 5.08%. The previous matcher assumed a constant time shift. Local matches showed an increasing offset, so it correctly failed its constant-offset validation but lacked a speed correction path.

The new path matches three-second windows throughout the reference, rejects ambiguous windows, robustly fits `comparison_time = offset + scale * reference_time`, requires consensus over at least half the reference, and confirms the result with a full-length audio match after resampling. Supported fitted scale range is 0.85–1.15. Audio export uses FFmpeg `atempo` and video export divides timestamps by the fitted scale. The reference is not sped up or slowed down. This is a single constant speed correction, not arbitrary warping.

For the attached videos:

- Reference video stream duration: 15.000 seconds (container duration is about 15.021 seconds).
- Comparison source interval: approximately 2.442–18.203 seconds.
- Comparison speed multiplier: 1.0507778.
- Both outputs: 15 seconds, 450 frames, 30 fps.
- Post-export feature matching in beginning/middle/end windows: about +20 ms residual, less than one 30 fps frame. These are audio checks, not visual ground-truth motion annotations.

`example-output/` contains the actual generated clips and alignment JSON. JSON filesystem paths record the execution environment where these outputs were generated; the packaged clips are in this folder.

## JSON mapping change — important for downstream code

Existing fields are retained; added fields make speed correction explicit:

```text
comparison_time = reference_time * comparison_time_scale + offset_seconds
```

For scale 1, this is exactly the original constant-offset convention. For non-unit scale, **offset_seconds alone no longer maps all original-source timestamps**. It is the comparison timestamp corresponding to reference time zero. Use `comparison_time_scale` as well when mapping back to originals.

Added fields:
- `comparison_time_scale`
- `time_mapping`
- `comparison_start_seconds`
- `comparison_end_seconds`

Overlap bounds remain reference seconds. Output length never exceeds the reference video, and both exports share the same length/frame count. If only partial overlap exists, only that interval is exported. Every output frame k corresponds to reference time `overlap_start_ref + k/30`; map that time to the original comparison using the formula above.

The existing frontend still runs and displays/downloads these outputs. It shows the speed-correction warning and full JSON, but its offset metric by itself does not explain speed correction. Future dance ranking should account for the fact that comparison timing has been normalized; retain the scale if assessing original performance speed.

## Validation and limits

Run from backend:

```bash
python -m pip install pytest httpx
python -m pytest -q
```

Tests cover original clean/noisy offsets, silent/unrelated audio rejection, API output downloads, real MP4 export, feature-only alignment, and speed differences in both directions. Actual uploaded videos were also processed and measured after export. No hard-coded offset, scale, or filename is used by the matcher.

Confidence remains a heuristic, not a probability. Edited songs, nonuniform speed changes, repeated sections, or heavy noise may still fail. Unsupported matches remain rejected. This update does not isolate music from background sounds; it finds and exports the matched video segment including its existing audio.

Deployment limitations remain unchanged: local/private prototype, one Uvicorn worker, disk-retained jobs, no authentication or public-service quotas, TikTok URL downloads dependent on availability.
