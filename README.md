# Motion — audio alignment for dance videos

A complete React + FastAPI application for uploading two dance videos or importing public TikTok links, aligning shared audio, and downloading synchronized 30 fps MP4s plus JSON metadata. Pose matching and dance ranking are intentionally the next stage.

## Run with Docker (recommended)

Install Docker Desktop, then from this directory:

```bash
docker compose up --build
```

Open http://localhost:8000. Interactive API documentation: http://localhost:8000/docs.

The frontend and backend are served from the same origin. Jobs and videos persist in the `motion-data` Docker volume. Stop with `docker compose down`; add `-v` only if you want to delete all saved videos and jobs.

## Run locally

Requirements: Python 3.11+, Node 20.19+ or 22.12+, FFmpeg and ffprobe on PATH. On macOS, `brew install ffmpeg` installs both media tools.

Terminal 1, from the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

Terminal 2, from the project directory:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to FastAPI. For a single-server local production build, run `npm run build` in `frontend`, then start FastAPI from `backend`; it automatically serves `../frontend/dist`.

## Use

1. Put the original choreography in **Reference video** and the other performance in **Comparison video**.
2. Drop/upload files, paste public TikTok links, or mix a link and a file. Dropped links are supported. Each video must have audio, last 3–180 seconds, and fit within 150 MB.
3. Choose **Align videos**. Processing runs in the background; the interface polls the job status.
4. Inspect the confidence and side-by-side preview. **Play together** plays reference audio only.
5. Download `alignment.json`, `reference_aligned.mp4`, and `comparison_aligned.mp4`.

TikTok may block downloads or require sign-in depending on region and video visibility. The importer uses yt-dlp without account cookies; if importing fails, upload downloaded video files. Only HTTPS TikTok URLs are accepted. No live TikTok import was tested during development.

## JSON contract

Each completed job writes a real `alignment.json` under `data/<job-id>/`:

```json
{
  "reference_video": "/app/data/<job-id>/reference.mp4",
  "comparison_video": "/app/data/<job-id>/comparison.mp4",
  "offset_seconds": 1.375,
  "overlap_start_ref": 0.0,
  "overlap_end_ref": 7.625,
  "reference_fps": 24.0,
  "comparison_fps": 60.0,
  "alignment_confidence": 0.96,
  "reference_aligned_video": "/app/data/<job-id>/reference_aligned.mp4",
  "comparison_aligned_video": "/app/data/<job-id>/comparison_aligned.mp4",
  "output_fps": 30,
  "output_frames": 228,
  "output_duration_seconds": 7.6,
  "export_end_ref": 7.6,
  "warnings": []
}
```

This is an illustrative schema example, not a result from your videos.

**Exact convention:** `comparison_time = reference_time + offset_seconds`.

- `+1.375` means reference time 0 matches comparison time 1.375; trim 1.375 seconds from the beginning of the comparison.
- `-1.25` means reference time 1.25 matches comparison time 0; trim 1.25 seconds from the reference.
- Overlap in reference coordinates is `[max(0, -offset), min(reference_duration, comparison_duration - offset)]`.
- `reference_video` / `comparison_video` are absolute backend filesystem paths to the original saved inputs; use `*_aligned_video` for later frame matching. Browser downloads use URLs from the status response, not these filesystem paths.
- Input FPS is the average FPS reported by ffprobe; it may describe a variable-frame-rate source.
- Output duration is rounded **down** to a whole number of 30 fps frames. At most 1/30 second of the overlap's tail is omitted. `overlap_end_ref` remains the full mathematical overlap; `export_end_ref` describes the actual exported interval.
- Output zero-based frame `k` represents approximately reference time `overlap_start_ref + k/30`, and comparison time `overlap_start_ref + offset_seconds + k/30`. Frame index 0 is the first frame. Source frame sampling limits temporal precision, especially with low-FPS inputs; 30 fps conversion does not synthesize new motion.

## API

### `POST /api/align` → 202

Multipart form. Supply exactly one source per slot:

| Slot | File field | Link field |
| --- | --- | --- |
| Reference | `reference_file` | `reference_url` |
| Comparison | `comparison_file` | `comparison_url` |

```bash
curl -X POST http://localhost:8000/api/align \
  -F 'reference_file=@reference.mp4' \
  -F 'comparison_file=@comparison.mp4'
```

Response: `{ "job_id": "…", "status_url": "/api/jobs/…" }`.

### `GET /api/jobs/{job_id}`

States: `queued`, `processing`, `completed`, `failed`. Completed responses include `result` (the JSON above) and `downloads` (three relative download URLs). Failed responses include an actionable `error`. Persist the job ID if calling the API directly. The browser's active job is not restored after a page reload.

### `GET /api/jobs/{job_id}/files/{filename}`

Downloads only the three generated output filenames. Unknown jobs/files return 404.

### `GET /api/health`

Reports whether ffmpeg and ffprobe are available.

## Alignment implementation

`backend/app/alignment.py`:

1. Probe stream durations, start timestamps, and frame rates.
2. Decode the first audio stream to 8 kHz mono float PCM, accounting for its start-time offset relative to the video stream.
3. Compute `scipy.signal.correlate(comparison, reference, method="fft")` and normalize each lag by the energies of its overlapping samples. Use absolute correlation to tolerate phase inversion and gain changes.
4. Require at least 3 seconds and at least 25% of the shorter clip at candidate lags, to avoid accidental tiny-overlap matches. Reject silent audio and normalized peaks below 0.18.
5. Confidence is the normalized peak strength multiplied by a distinctiveness factor comparing the strongest peak outside a ±100 ms neighborhood. It is a heuristic in [0,1], **not a calibrated probability** or dance-match score. Scores below 0.65 display a review warning.
6. Compute the shared interval and use **one FFmpeg command with two inputs and two outputs**: trim video/audio, reset timestamps, convert to 30 fps, enforce equal frame counts, and re-encode H.264/AAC. Odd image dimensions are rounded down to even values for H.264.
7. Save JSON only after successful exports.

This MVP assumes identical music at the same playback speed and a constant time offset. Edited/remixed music, time stretching, strong voiceovers, microphone-recorded music, repeated choruses, or shared silence may fail or produce an ambiguous offset. Manually review uncertain matches. Speed-drift estimation, feature-based matching, and motion analysis are future work. Two browser video elements provide a review preview, not a frame-accurate playback clock; downloaded clips are the alignment artifacts.

Primary implementation references:
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlate.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlation_lags.html
- https://www.ffmpeg.org/ffmpeg-filters.html

## Tests

From `backend` with the virtual environment active:

```bash
pip install pytest httpx
python -m pytest -q
```

Seven tests cover positive/negative/zero offset with gain/noise, silence/unrelated audio rejection, real mixed-FPS FFmpeg input/output, equal exported frame counts and zero timestamps, residual audio alignment, API submission/polling/download, and invalid inputs. Synthetic test videos are created by the tests. Frontend production build: `cd frontend && npm run build`.

Verification in the development environment: seven tests passed; React production build passed. Browser interaction, live TikTok downloads, and a Docker image build were not verified here.

## Project structure

```
backend/app/alignment.py       Signal processing and two-output FFmpeg export
backend/app/main.py            Uploads, TikTok importing, job status, downloads
backend/tests/test_alignment.py
frontend/src/main.jsx          React input, job, and result interface
frontend/src/style.css         Responsive styling
Dockerfile                    Builds React and serves it with FastAPI
compose.yaml                  Local persistent single-server setup
```

## Deployment scope

This is a local/private prototype. Docker binds to loopback by default. It needs a server/container that runs Python and FFmpeg; it cannot run entirely on static hosting or Cloudflare Workers.

Run one Uvicorn worker: jobs use an in-process queue (two active jobs, eight retained task slots), with persistent status files. On restart, interrupted jobs are marked failed. Files are retained until explicitly deleted; monitor disk space and remove old job directories when no longer needed. Do not remove jobs while they are processing.

Before exposing this publicly, add authentication/authorization, reverse-proxy request-size limits, per-user quotas, durable queue workers, retention/cleanup, and network isolation for URL downloads. Application URL validation is not a substitute for outbound firewall restrictions on downloader redirects. Uploaded media and external downloads should be processed in isolated workers. Dependency ranges are intentional; `frontend/package-lock.json` locks the frontend install, while Python dependencies should be locked for your deployment environment.
