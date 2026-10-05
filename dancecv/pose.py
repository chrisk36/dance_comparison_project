"""Pose extraction with MediaPipe PoseLandmarker (VIDEO mode), cached per video file."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from dancecv.config import CACHE_DIR, MODELS_DIR
from dancecv.video_io import iter_frames, probe

N_LANDMARKS = 33
CACHE_VERSION = 1


@dataclass
class PoseSeq:
    """Per-frame poses of one video.

    kp:    (T, P, 33, 3) = x_px, y_px, visibility; NaN where no pose was detected.
    world: (T, P, 33, 3) = MediaPipe world landmarks in metres (hip-centred); NaN if missing.
    P is the number of people (always 1 for the MVP).
    """

    t: np.ndarray
    kp: np.ndarray
    world: np.ndarray
    width: int
    height: int
    fps: float

    def __len__(self) -> int:
        return len(self.t)

    def save(self, path: Path) -> None:
        np.savez_compressed(path, t=self.t, kp=self.kp, world=self.world,
                            meta=np.array([self.width, self.height, self.fps, CACHE_VERSION]))

    @classmethod
    def load(cls, path: Path) -> "PoseSeq":
        d = np.load(path)
        w, h, fps, _ = d["meta"]
        return cls(t=d["t"], kp=d["kp"], world=d["world"], width=int(w), height=int(h), fps=float(fps))


def _file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _make_landmarker(model: str):
    from mediapipe.tasks.python import BaseOptions, vision

    model_path = MODELS_DIR / f"pose_landmarker_{model}.task"
    if not model_path.exists():
        raise FileNotFoundError(f"{model_path} missing; run scripts/download_models.sh {model}")
    opts = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
    )
    return vision.PoseLandmarker.create_from_options(opts)


def extract_poses(video: str | Path, model: str = "full", use_cache: bool = True,
                  progress: Optional[Callable[[float], None]] = None) -> PoseSeq:
    """Run pose estimation on every frame of `video` (cached by file content + model)."""
    import cv2
    import mediapipe as mp

    video = Path(video)
    cache = CACHE_DIR / f"{_file_hash(video)}_{model}_mp{mp.__version__}_v{CACHE_VERSION}.npz"
    if use_cache and cache.exists():
        return PoseSeq.load(cache)

    info = probe(video)
    n_est = max(1, int(round(info.duration * info.fps)))
    ts, kps, worlds = [], [], []
    last_ms = -1
    with _make_landmarker(model) as landmarker:
        for idx, t, frame in iter_frames(video):
            h, w = frame.shape[:2]
            ms = max(int(round(t * 1000)), last_ms + 1)  # VIDEO mode needs strictly increasing ms
            last_ms = ms
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            res = landmarker.detect_for_video(image, ms)

            kp = np.full((1, N_LANDMARKS, 3), np.nan, dtype=np.float32)
            world = np.full((1, N_LANDMARKS, 3), np.nan, dtype=np.float32)
            if res.pose_landmarks:
                # Image-normalised x/y are relative to width/height separately; convert to pixels
                # so geometry is isotropic regardless of aspect ratio.
                kp[0] = [(lm.x * w, lm.y * h, lm.visibility) for lm in res.pose_landmarks[0]]
                world[0] = [(lm.x, lm.y, lm.z) for lm in res.pose_world_landmarks[0]]
            ts.append(t)
            kps.append(kp)
            worlds.append(world)
            if progress and idx % 15 == 0:
                progress(min(1.0, idx / n_est))

    seq = PoseSeq(t=np.asarray(ts, dtype=np.float64), kp=np.stack(kps), world=np.stack(worlds),
                  width=info.width, height=info.height, fps=info.fps)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    seq.save(cache)
    if progress:
        progress(1.0)
    return seq
