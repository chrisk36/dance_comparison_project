import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .alignment import align_pair

ROOT = Path(os.getenv('DATA_DIR', './data')).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
MAX_BYTES = 150 * 1024 * 1024
app = FastAPI(title='Motion / Audio Alignment', version='1.0.0')
# One process, two concurrent jobs; job states survive process restarts as JSON.
slots = asyncio.Semaphore(2)
tasks = set()


def state(directory, **value):
    temp = directory/'status.tmp'
    temp.write_text(json.dumps(value))
    temp.replace(directory/'status.json')


def validate_url(url):
    p = urlparse(url)
    if p.scheme != 'https' or p.hostname not in {'www.tiktok.com', 'tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'} or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Use an HTTPS TikTok link, or upload the video file.')
    if not p.path or p.path == '/':
        raise ValueError('Paste a link to an individual TikTok video.')
    return url


def download(url, destination):
    validate_url(url)
    try:
        subprocess.run([sys.executable, '-m', 'yt_dlp', '--no-playlist', '--no-progress', '--no-warnings',
                        '--max-filesize', str(MAX_BYTES), '--socket-timeout', '20', '--retries', '1',
                        '--match-filter', 'duration <= 180', '-f', 'b[ext=mp4]/b',
                        '-o', str(destination), '--', url], check=True, capture_output=True, timeout=150)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError('TikTok could not be downloaded. Download the video yourself and use Upload video.') from exc
    if not destination.exists() or destination.stat().st_size > MAX_BYTES:
        raise ValueError('TikTok video is unavailable or exceeds 150 MB.')


async def process(directory, urls):
    async with slots:
        try:
            state(directory, status='processing', stage='Preparing audio and finding the shared soundtrack')
            for name, url in urls.items():
                if url:
                    await asyncio.to_thread(download, url, directory/f'{name}.mp4')
            result = await asyncio.to_thread(align_pair, directory/'reference.mp4', directory/'comparison.mp4', directory)
            state(directory, status='completed', result=result,
                  downloads={name: f'/api/jobs/{directory.name}/files/{name}' for name in ['alignment.json', 'reference_aligned.mp4', 'comparison_aligned.mp4']})
        except Exception as exc:
            state(directory, status='failed', error=str(exc) if isinstance(exc, ValueError) else 'Processing failed. Check the server logs and try another video.')
            if not isinstance(exc, ValueError):
                import logging
                logging.exception('Alignment job failed')


@app.on_event('startup')
async def recover():
    for path in ROOT.glob('*/status.json'):
        try:
            if json.loads(path.read_text())['status'] in ('queued', 'processing'):
                state(path.parent, status='failed', error='Server restarted during processing. Please submit again.')
        except (ValueError, KeyError):
            pass


@app.get('/api/health')
def health():
    return {'status': 'ok', 'ffmpeg': bool(shutil.which('ffmpeg')), 'ffprobe': bool(shutil.which('ffprobe'))}


@app.post('/api/align', status_code=202)
async def create(reference_file: UploadFile | None = File(None), comparison_file: UploadFile | None = File(None),
                 reference_url: str = Form(''), comparison_url: str = Form('')):
    sources = [('reference', reference_file, reference_url.strip()), ('comparison', comparison_file, comparison_url.strip())]
    for name, upload, url in sources:
        if bool(upload) == bool(url):
            raise HTTPException(422, f'Provide exactly one file or TikTok link for {name}.')
        if url:
            try:
                validate_url(url)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
    if len(tasks) >= 8:
        raise HTTPException(429, 'The processing queue is full. Please try again shortly.')
    directory = ROOT/uuid.uuid4().hex
    directory.mkdir()
    try:
        for name, upload, _ in sources:
            if upload:
                count = 0
                with (directory/f'{name}.mp4').open('wb') as out:
                    while chunk := await upload.read(1024*1024):
                        count += len(chunk)
                        if count > MAX_BYTES:
                            raise HTTPException(413, 'Each video must be under 150 MB.')
                        out.write(chunk)
                await upload.close()
                if count == 0:
                    raise HTTPException(422, 'The uploaded file is empty.')
        state(directory, status='queued', stage='Waiting for a processing slot')
        task = asyncio.create_task(process(directory, {n: u for n, _, u in sources}))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {'job_id': directory.name, 'status_url': f'/api/jobs/{directory.name}'}
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def job_dir(job_id):
    if not re.fullmatch('[0-9a-f]{32}', job_id) or not (ROOT/job_id/'status.json').exists():
        raise HTTPException(404, 'Job not found.')
    return ROOT/job_id


@app.get('/api/jobs/{job_id}')
def status(job_id: str):
    return json.loads((job_dir(job_id)/'status.json').read_text())


@app.get('/api/jobs/{job_id}/files/{filename}')
def output(job_id: str, filename: str):
    directory = job_dir(job_id)
    if filename not in {'alignment.json', 'reference_aligned.mp4', 'comparison_aligned.mp4'} or not (directory/filename).exists():
        raise HTTPException(404, 'Output not found.')
    return FileResponse(directory/filename, media_type='application/json' if filename.endswith('.json') else 'video/mp4', filename=filename)


frontend = Path(os.getenv('FRONTEND_DIR', '../frontend/dist'))
if frontend.is_dir():
    app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
