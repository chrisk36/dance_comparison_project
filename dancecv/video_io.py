"""Video/audio helpers built on ffprobe/ffmpeg and OpenCV."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

TARGET_FPS = 30.0


@dataclass
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{proc.stderr.decode(errors='replace')[-2000:]}")
    return proc


def probe(path: str | Path) -> VideoInfo:
    out = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]).stdout
    info = json.loads(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    num, den = video.get("avg_frame_rate", "0/1").split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    if not fps:
        num, den = video["r_frame_rate"].split("/")
        fps = float(num) / float(den)
    w, h = int(video["width"]), int(video["height"])
    # Phone videos may carry a rotation; OpenCV applies it on decode, so report display size.
    rotation = 0
    for sd in video.get("side_data_list", []):
        rotation = int(sd.get("rotation", rotation))
    if abs(rotation) % 180 == 90:
        w, h = h, w
    return VideoInfo(
        path=str(path),
        width=w,
        height=h,
        fps=fps,
        duration=float(info["format"]["duration"]),
        has_audio=any(s["codec_type"] == "audio" for s in info["streams"]),
    )


def decode_audio_mono(path: str | Path, sr: int = 22050) -> np.ndarray:
    """Decode a file's audio track to a mono float32 array at `sr` Hz."""
    raw = _run([
        "ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
        "-f", "f32le", "-",
    ]).stdout
    return np.frombuffer(raw, dtype=np.float32)


def trim_video(src: str | Path, dst: str | Path, start: float, duration: float,
               fps: float = TARGET_FPS) -> None:
    """Cut [start, start+duration) from src and re-encode at a constant `fps` (H.264, web-playable)."""
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{max(start, 0.0):.4f}", "-i", str(src), "-t", f"{duration:.4f}",
        "-vf", f"fps={fps}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(dst),
    ])


def hflip_video(src: str | Path, dst: str | Path) -> None:
    """Horizontally mirrored copy of a video (audio untouched)."""
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "hflip",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(dst),
    ])


def side_by_side_preview(left: str | Path, right: str | Path, dst: str | Path,
                         height: int = 640, duration: float | None = None) -> None:
    """Debug preview: two clips scaled to the same height, side by side, audio of both mixed.

    If the clips are aligned the mixed audio sounds like a single track (no echo/flam).
    """
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(left), "-i", str(right)]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += [
        "-filter_complex",
        f"[0:v]scale=-2:{height},setsar=1[l];[1:v]scale=-2:{height},setsar=1[r];"
        f"[l][r]hstack=inputs=2:shortest=1[v];[0:a][1:a]amix=inputs=2:duration=shortest[a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(dst),
    ]
    _run(cmd)


def iter_frames(path: str | Path) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield (frame_index, timestamp_seconds, bgr_frame) using decoder timestamps."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or TARGET_FPS
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            # Some backends report 0 for every frame; fall back to index / fps.
            t = t_ms / 1000.0 if (t_ms > 0 or idx == 0) else idx / fps
            yield idx, t, frame
            idx += 1
    finally:
        cap.release()
