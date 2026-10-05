# Dance Sync (MVP)

Compares a dance video against a reference video. The two videos are aligned by their audio, then the app scores how well the dancer's movement matches. The output is a 0–100 score and the timestamps where the dancer falls out of sync.

How the parts plug together (alignment ↔ scoring ↔ UI) is in **[CONTRACT.md](CONTRACT.md)**.

## Setup
```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
scripts/download_models.sh            # MediaPipe pose models -> models/
(cd frontend && npm install)
```
- **Requirements:** ffmpeg must be on your PATH.
- **mediapipe is pinned to 0.10.33.** Version 1.0.x crashes on macOS.
- **Test videos:** `test_videos/` is gitignored. Copy the pair in as `test_videos/ref.mp4` and `test_videos/comp.mp4`.

## Run from the command line
```bash
.venv/bin/python run_pipeline.py test_videos/ref.mp4 test_videos/comp.mp4      # aligns using the audio
.venv/bin/python run_pipeline.py --alignment path/to/alignment.json            # uses an existing alignment
.venv/bin/python sanity_checks.py --debug                                      # self / flipped / comp / wrong-offset checks
```
Each run writes these files to `outputs/runs/<ref>_vs_<comp>/`:
- `results.json`
- `debug.mp4`: side by side, with skeletons drawn
- `timeline.png`
- `flagged_strip.png`

## Run the app
```bash
.venv/bin/uvicorn server.app:app --port 8000        # API
(cd frontend && npm run dev)                        # UI at http://localhost:5173 (proxies /api)
```
To use Wei's alignment instead of the stub: `DANCECV_ALIGNER=audio .venv/bin/uvicorn server.app:app --port 8000`. This loads `dancecv/alignment/audio.py::align`.

## Layout
| Path | What |
|---|---|
| `dancecv/alignment/stub.py` | stand-in for the alignment step: offset 0, a fixed `--offset`, or audio cross-correlation |
| `dancecv/pose.py` | MediaPipe PoseLandmarker; results cached in `outputs/cache/` |
| `dancecv/normalize.py` | cleans up keypoints, normalizes to hip center and torso scale, mirrors |
| `dancecv/scoring.py` | limb-direction similarity, timing tolerance, chooses mirrored or not |
| `dancecv/segments.py` | finds out-of-sync segments and stretches with no pose |
| `dancecv/pipeline.py` | `run_from_alignment(alignment.json) -> results.json` |
| `dancecv/config.py` | every tunable threshold |
| `server/app.py` | FastAPI |
| `frontend/` | React + Vite + Tailwind |

## Scoring in one paragraph
- **Comparison:** for each frame, 12 limb directions are compared (arms, legs, shoulder and hip lines, torso, head). A small angle error (≤15°) is free, and a limb scores 0 at 45°.
- **Weighting:** limbs are weighted by how much they move in the reference, so static legs don't inflate the score of an arm-driven dance.
- **Timing tolerance:** the comparison dancer may be up to ±0.2 s early or late. The chosen lag must hold over a 0.5 s neighbourhood.
- **Mirroring:** the mirrored orientation is used if it beats the original by more than 3 points.
- **Out-of-sync segments:** stretches where the 0.2 s-smoothed score stays below 60 for at least 0.3 s.
