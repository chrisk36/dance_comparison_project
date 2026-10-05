# Motion — Audio Alignment for Dance Videos

Motion is a React + FastAPI application that finds shared music in two dance videos and exports synchronized clips for later computer-vision analysis.

Upload a reference performance and a comparison performance, or provide public TikTok links. The backend locates the matching audio, estimates their time offset and—when supported by the audio—corrects a constant playback-speed difference. Both clips are trimmed to the shared reference interval and exported at **30 fps**, with JSON metadata for downstream matching and ranking.

**Current scope:** audio-based temporal alignment. Pose extraction, movement scoring, dancer synchronization analysis, camera alignment, and dance ranking are not implemented.

## Features

- Two drag-and-drop video slots, with file uploads or public TikTok links.
- Background processing with job status polling.
- Precise waveform matching for clean shared soundtracks.
- Log-mel feature matching for noisy and speaker-recorded audio.
- Constant playback-speed correction using consistent matches across multiple sections.
- Reference-bounded exports: a longer comparison does not make the output longer than the reference.
- Side-by-side playback, MP4 downloads, and alignment JSON.
- Confidence warnings for weaker accepted matches; unsupported matches fail with an error.

The application locates music within a video; it does **not** separate music from voices or background noise.

## Tech stack

| Component | Technology |
| --- | --- |
| Frontend | React, Vite, CSS, Lucide icons |
| API | Python, FastAPI, Uvicorn |
| Audio analysis | NumPy, SciPy |
| Media inspection and export | FFprobe, FFmpeg |
| TikTok import | yt-dlp |
| Tests | pytest, FastAPI TestClient, HTTPX |

## Local setup — no Docker required

The commands below are for macOS/Linux. Use the full project, with the latest `backend/app/alignment.py` installed. A backend-only update archive does not contain the React frontend.

### 1. Install prerequisites

You need Python, Node.js/npm, and FFmpeg/ffprobe. The backend was tested with Python 3.12. The project frontend uses Vite 6; Node 22.12+ is a suitable setup target.

If you use Homebrew on macOS:

```bash
brew install python@3.12 node ffmpeg
```

Verify the tools:

```bash
python3.12 --version
node --version
npm --version
ffmpeg -version
ffprobe -version
```

### 2. Set up and start the backend

Open Terminal and go to the extracted project folder. Adjust this path if necessary:

```bash
cd ~/Downloads/motion-align
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

Wait for **Application startup complete**. Leave this terminal running.

Run Uvicorn from `backend`, which contains the `app` directory. Using `python -m uvicorn` also ensures it uses the active Python environment.

### 3. Start the frontend

Open a second Terminal window:

```bash
cd ~/Downloads/motion-align/frontend
npm ci
npm run dev
```

Open the URL printed by Vite, normally **http://localhost:5173**. Vite forwards `/api` requests to **http://127.0.0.1:8000**.

- API documentation: http://localhost:8000/docs
- Backend health check: http://localhost:8000/api/health

Both terminals must remain running. Press Ctrl+C in each to stop.

### Restart an existing installation

Backend terminal:

```bash
cd ~/Downloads/motion-align
source .venv/bin/activate
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

Frontend terminal:

```bash
cd ~/Downloads/motion-align/frontend
npm run dev
```

You do not need to recreate the virtual environment or reinstall dependencies each time.

## Updating the backend

1. Stop the backend with Ctrl+C.
2. Replace `backend/app/alignment.py` with the latest supplied version.
3. Keep your frontend, virtual environment, and existing `backend/data` directory.
4. Restart the backend from its `backend` directory.

The noise-robust and speed-correction updates use the existing NumPy/SciPy dependencies. The latest API keeps existing fields and adds speed-mapping metadata; see the JSON contract below.

## Using the application

1. Add the original choreography to **Reference video**.
2. Add the performance you want to compare to **Comparison video**.
3. Choose a file or TikTok link for each slot. Mixing source types is supported.
4. Click **Align videos** and keep the tab open while processing.
5. Review the confidence, warnings, and side-by-side preview.
6. Download `reference_aligned.mp4`, `comparison_aligned.mp4`, and `alignment.json`.

Both inputs must contain video and audio, last **3–180 seconds**, and fit within **150 MB each**. FFmpeg must be able to decode the uploaded media; MP4, MOV, and WebM are common supported inputs. Filenames on disk use `.mp4`, but FFmpeg probes the actual uploaded content.

Only HTTPS TikTok links on the allowed TikTok hosts are accepted. Private videos, unavailable videos, region restrictions, or TikTok download blocking can prevent import. If a link fails, download a permitted copy yourself and upload the video file. Live TikTok importing has not been verified in the development environment.

**Play together** mutes comparison audio. Browser playback is a review aid, not a frame-accurate shared playback clock; use the exported files for analysis. Reloading the page does not restore the current job in the interface.

## How matching works

The implementation is in `backend/app/alignment.py`.

1. **Inspect media.** FFprobe reads video duration, input frame rate, and audio/video stream start timestamps.
2. **Decode audio.** FFmpeg extracts 8 kHz mono samples, accounting for the audio stream's start relative to the video.
3. **Try a constant offset.** Overlap-normalized FFT waveform correlation provides precise matches for shared digital audio. Weaker waveform results fall back to normalized log-mel temporal features with 10 ms hops.
4. **Validate the pattern.** Feature matching compares alternative peaks and checks evidence in separate sections. Candidate overlaps must cover at least three seconds and at least 25% of the shorter audio.
5. **Check timing drift.** Three-second reference windows are matched against the comparison. Consistent matches across at least half the reference can support a robust offset-and-speed fit. The fitted speed range is **0.85–1.15**. A full-reference match against resampled comparison audio confirms the proposed mapping. When drift cannot be established, a valid constant-offset match may still be used.
6. **Export shared content.** One FFmpeg command trims and re-encodes both videos. The comparison video timestamps and audio tempo are corrected when necessary. Both outputs have equal frame counts, reset timestamps, H.264 video, AAC audio, and 30 fps.
7. **Write metadata.** The backend saves `alignment.json` after successful exports.

The matcher estimates a single constant speed multiplier, not arbitrary nonlinear time warping. Confidence is a heuristic score in **[0,1]**, not a probability or a dance-quality score. Scores below **0.65** produce a review warning. Scores from different matching paths are not statistically calibrated against each other.

## Reference-bounded trimming

The backend searches the **full permitted comparison audio**. It does not truncate the comparison to the reference length before searching, because the matching segment might occur later.

Let:

- `R` = reference video duration
- `C` = comparison video duration
- `o` = offset in seconds
- `s` = comparison time scale, always positive

The mapping and shared interval are:

```text
comparison_time = reference_time * s + o

start_ref = max(0, -o / s)
end_ref   = min(R, (C - o) / s)
```

The export length is `floor((end_ref - start_ref) * 30) / 30`. It never exceeds the reference duration. Less than one output frame may be dropped from the tail to produce equal whole-frame lengths. If less than three seconds overlap, the job fails.

If the comparison contains the entire reference segment, the full reference video interval is exported. Otherwise, both exports contain only their shared interval. Duration is based on the video stream when available; a container can report a slightly longer duration due to its audio track.

## JSON contract

Each successful job writes `data/<job-id>/alignment.json`. Example values below are rounded from the verified sample pair; paths are illustrative server paths:

```json
{
  "reference_video": "/app/data/example/reference.mp4",
  "comparison_video": "/app/data/example/comparison.mp4",
  "offset_seconds": 2.441745,
  "comparison_time_scale": 1.050778,
  "time_mapping": "comparison_time = reference_time * comparison_time_scale + offset_seconds",
  "comparison_start_seconds": 2.441745,
  "comparison_end_seconds": 18.203412,
  "overlap_start_ref": 0.0,
  "overlap_end_ref": 15.0,
  "reference_fps": 30.0,
  "comparison_fps": 24.0,
  "alignment_confidence": 0.704622,
  "reference_aligned_video": "/app/data/example/reference_aligned.mp4",
  "comparison_aligned_video": "/app/data/example/comparison_aligned.mp4",
  "output_fps": 30,
  "output_frames": 450,
  "output_duration_seconds": 15.0,
  "export_end_ref": 15.0,
  "warnings": [
    "Comparison playback speed corrected to match the reference."
  ]
}
```

| Field | Meaning |
| --- | --- |
| `reference_video`, `comparison_video` | Absolute server filesystem paths to saved original inputs |
| `offset_seconds` | Original comparison time corresponding to reference time zero |
| `comparison_time_scale` | Multiplier mapping reference seconds to original comparison seconds; 1 means no speed correction |
| `time_mapping` | Explicit source-timestamp mapping formula |
| `comparison_start_seconds`, `comparison_end_seconds` | Original comparison interval actually used in the export |
| `overlap_start_ref`, `overlap_end_ref` | Full shared interval in original reference seconds |
| `reference_fps`, `comparison_fps` | Original average frame rates reported by FFprobe |
| `alignment_confidence` | Heuristic audio-match score, 0–1 |
| `reference_aligned_video`, `comparison_aligned_video` | Absolute server paths to the exported MP4 files |
| `output_fps`, `output_frames` | Shared export frame rate and frame count |
| `output_duration_seconds` | Shared export duration after whole-frame rounding |
| `export_end_ref` | Actual exported end in reference seconds |
| `warnings` | Review guidance, including speed correction and limited confidence |

### Important compatibility change

The original mapping was:

```text
comparison_time = reference_time + offset_seconds
```

It remains valid **only when `comparison_time_scale == 1`**. With speed correction, downstream code must use:

```text
comparison_time = reference_time * comparison_time_scale + offset_seconds
```

A scale of `1.050778` means the comparison segment spans about 5.08% more source time than the reference and is played approximately 1.050778× faster in the export. The original reference speed is preserved.

For zero-based output frame `k`:

```text
reference_source_time  = overlap_start_ref + k / output_fps
comparison_source_time = reference_source_time * comparison_time_scale + offset_seconds
```

Input frame sampling and audio-match accuracy limit alignment precision. Conversion to 30 fps may duplicate or drop frames; it does not create new motion information. Retain the speed multiplier when evaluating original dance speed, since exported comparison timing has been normalized.

The frontend's offset metric alone does not convey speed correction. Read its warning and full metadata. Server filesystem paths are not browser URLs; use `downloads` from the status response for browser access.

## API

### Submit a job

`POST /api/align` accepts multipart form data and returns **202**. Supply exactly one file or URL per slot:

| Slot | Upload field | Link field |
| --- | --- | --- |
| Reference | `reference_file` | `reference_url` |
| Comparison | `comparison_file` | `comparison_url` |

```bash
curl -X POST http://localhost:8000/api/align \
  -F 'reference_file=@reference.mp4' \
  -F 'comparison_file=@comparison.mp4'
```

Response:

```json
{
  "job_id": "<job-id>",
  "status_url": "/api/jobs/<job-id>"
}
```

### Poll a job

`GET /api/jobs/{job_id}` returns `queued`, `processing`, `completed`, or `failed`.

Completed responses include `result` (the alignment metadata) and `downloads`:

```json
{
  "alignment.json": "/api/jobs/<job-id>/files/alignment.json",
  "reference_aligned.mp4": "/api/jobs/<job-id>/files/reference_aligned.mp4",
  "comparison_aligned.mp4": "/api/jobs/<job-id>/files/comparison_aligned.mp4"
}
```

These relative URLs are resolved against the application origin. Failed jobs include an `error` message. Keep the job ID to retrieve results after leaving the page.

### Download a result

`GET /api/jobs/{job_id}/files/{filename}` serves the three output files above. Unknown jobs or unsupported filenames return 404.

### Check the backend

`GET /api/health` reports backend status and whether FFmpeg/ffprobe are available. A response with `"ffmpeg": false` or `"ffprobe": false` means media processing is not ready even if the server is running.

Request errors include missing/conflicting sources or invalid links (422), oversized uploads (413), and a full job queue (429). Media-processing errors occur asynchronously and are reported through job status.

## Troubleshooting

### `ModuleNotFoundError: No module named 'app'`

Start the backend from the directory containing `app/`:

```bash
cd ~/Downloads/motion-align
source .venv/bin/activate
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

If the problem persists, check that you have `backend/app/main.py` and have not accidentally created `backend/backend/app/` while extracting an update.

### `Unexpected token 'I', "Internal S"... is not valid JSON`

The frontend received a plain-text server/proxy error rather than JSON. This message is not the underlying cause.

1. Confirm the backend reached **Application startup complete**.
2. Open http://localhost:8000/api/health.
3. Inspect the backend terminal traceback; if none appears, inspect the Vite terminal for a proxy connection error.
4. Fix the underlying server/startup error and submit again.

The current frontend does not gracefully parse every non-JSON error response.

### No reliable shared musical pattern

Use the latest `alignment.py`. Earlier versions required one constant offset and could reject shared songs with different playback speeds. The current version supports a limited constant speed difference, but significant edits, heavy noise, repeated sections, or nonuniform drift may still fail. Use longer, clearer shared music and inspect warnings for accepted matches.

### TikTok download fails

Upload the video file instead. TikTok availability and access restrictions can prevent yt-dlp from retrieving a public link.

### Missing modules or a different Python environment

Activate `.venv`, use `python -m pip`, and start with `python -m uvicorn`. To verify the selected interpreter:

```bash
python -c "import sys; print(sys.executable)"
```

### FFmpeg cannot be found

Install FFmpeg, restart the terminal if PATH changed, and verify both `ffmpeg -version` and `ffprobe -version` before restarting FastAPI.

## Project structure

```text
motion-align/
  backend/
    app/
      alignment.py             Audio matching, speed mapping, and media exports
      main.py                  Uploads, TikTok import, job state, and downloads
    tests/
      test_alignment.py        Original offset, API, and export tests
      test_noisy_alignment.py  Noisy audio, feature-only, and speed-mapping tests
    requirements.txt
    data/                      Generated at runtime; do not commit
  frontend/
    src/
      main.jsx                 React upload, progress, preview, and results UI
      style.css                Responsive styles
    index.html
    package.json
    package-lock.json
    vite.config.js             Development API proxy
  Dockerfile
  compose.yaml
  README.md
```

The fixed-backend download also includes `example-output/` with the verified pair and JSON; this is a sample artifact, not a required runtime directory.

## Tests and verification

From `backend`, with the virtual environment active:

```bash
python -m pip install pytest httpx
python -m pytest -q
```

The latest backend passed **14 tests**, covering clean positive/negative/zero offsets, noisy recordings, silence/unrelated audio rejection, feature-only fallback, constant speed differences in both directions, API submission/downloads, and real FFmpeg exports.

A real uploaded pair was also processed successfully:

| Measurement | Result |
| --- | --- |
| Reference video duration | 15.000 seconds |
| Matched comparison interval | Approximately 2.442–18.203 seconds |
| Comparison speed multiplier | Approximately 1.050778 |
| Export length | 15 seconds each |
| Export frame rate/count | 30 fps / 450 frames each |
| Residual audio offset in beginning/middle/end checks | Approximately 20 ms |

This is an audio-based verification on one real pair, not a general accuracy benchmark or visual pose-alignment ground truth. Thresholds and confidence remain heuristic.

Frontend build check:

```bash
cd frontend
npm run build
```

The frontend production build passed during initial implementation. Browser interactions, live TikTok downloads, and Docker image startup were not verified in the development environment.

## Single-server build

Build React from `frontend`:

```bash
npm ci
npm run build
```

Then start FastAPI from `backend` without development reload:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

When `../frontend/dist` exists at startup, FastAPI serves it at http://localhost:8000 alongside the API. Restart the backend after creating the build.

## Optional Docker setup

If you later install Docker:

```bash
docker compose up --build
```

Run from the project root and open http://localhost:8000. The Compose configuration binds to loopback and stores jobs in the `motion-data` volume. `docker compose down` stops the service; adding `-v` also deletes the saved volume.

## Storage and deployment scope

This is a local/private prototype requiring a host that can execute Python and FFmpeg. It cannot run entirely on static hosting or a Cloudflare Worker.

| Setting | Default / behavior |
| --- | --- |
| `DATA_DIR` | `./data`, relative to the backend process working directory |
| `FRONTEND_DIR` | `../frontend/dist`, relative to the backend process working directory |
| Active processing | Two jobs per process |
| Pending plus active task limit | Eight |
| Uvicorn workers | Use one |
| Retention | Files remain until explicitly removed |
| Restart recovery | Previously queued/processing jobs are marked failed |

The queue is in-process; job status is persisted as JSON. Do not delete a job directory while it is processing. There is no automatic cleanup or resume after restart.

Before public deployment, add authentication, per-user authorization/quotas, request-size limits at a reverse proxy, a durable worker queue, retention, and isolation for downloaded/uploaded media processing. Restrict downloader network access; input URL validation alone does not control redirects. Frontend dependencies are locked by `package-lock.json`; Python requirements use version ranges and should be locked for a deployment environment.

## Next development stage

- Extract body keypoints from each aligned frame.
- Normalize body position and scale before comparing poses.
- Calculate joint-angle and movement similarities.
- Report timing and movement differences, retaining original speed metadata.
- Add multi-dancer tracking and camera-motion handling.

## Implementation references

- [SciPy correlation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlate.html)
- [SciPy correlation lags](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlation_lags.html)
- [FFmpeg filters](https://www.ffmpeg.org/ffmpeg-filters.html)
