"""Keypoint cleanup, body-relative normalisation and the mirror transform."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter

from dancecv.config import Params

# Joint subset used for scoring (MediaPipe landmark indices).
JOINTS: dict[str, int] = {
    "nose": 0,
    "l_shoulder": 11, "r_shoulder": 12,
    "l_elbow": 13, "r_elbow": 14,
    "l_wrist": 15, "r_wrist": 16,
    "l_hip": 23, "r_hip": 24,
    "l_knee": 25, "r_knee": 26,
    "l_ankle": 27, "r_ankle": 28,
}
JOINT_NAMES = list(JOINTS)
J = {name: i for i, name in enumerate(JOINT_NAMES)}  # name -> column in the subset array
MP_INDICES = np.array([JOINTS[n] for n in JOINT_NAMES])

# Mirror = negate x and swap left/right labels.
MIRROR_PERM = np.array([
    J[n.replace("l_", "r_", 1) if n.startswith("l_") else n.replace("r_", "l_", 1) if n.startswith("r_") else n]
    for n in JOINT_NAMES
])


@dataclass
class CleanPose:
    pts: np.ndarray  # (T, J, 2) pixel coords, NaN where missing/low-confidence
    norm: np.ndarray  # (T, J, 2) hip-centred, torso-length-scaled; NaN where undefined


def _interp_short_gaps(x: np.ndarray, max_gap: int) -> np.ndarray:
    """Linearly fill interior NaN runs of length <= max_gap along axis 0 of a 1-D series."""
    x = x.copy()
    isnan = np.isnan(x)
    if not isnan.any() or isnan.all():
        return x
    idx = np.arange(len(x))
    valid = ~isnan
    filled = np.interp(idx, idx[valid], x[valid])
    # Only accept fills inside runs that are short and bounded on both sides.
    run_start = None
    for i in range(len(x) + 1):
        if i < len(x) and isnan[i]:
            if run_start is None:
                run_start = i
        elif run_start is not None:
            if run_start > 0 and i < len(x) and (i - run_start) <= max_gap:
                x[run_start:i] = filled[run_start:i]
            run_start = None
    return x


def _drop_short_islands(present: np.ndarray, min_len: int) -> np.ndarray:
    """Return a mask that removes runs of True shorter than min_len."""
    keep = present.copy()
    i, n = 0, len(present)
    while i < n:
        if present[i]:
            j = i
            while j < n and present[j]:
                j += 1
            if j - i < min_len:
                keep[i:j] = False
            i = j
        else:
            i += 1
    return keep


def clean(kp: np.ndarray, params: Params, person: int = 0) -> CleanPose:
    """kp: (T, P, 33, 3) from PoseSeq -> cleaned subset + normalised coordinates."""
    sub = kp[:, person, MP_INDICES, :].astype(np.float64)  # (T, J, 3)
    pts = sub[..., :2].copy()
    vis = sub[..., 2]

    detected = ~np.isnan(vis).all(axis=1)
    keep = _drop_short_islands(detected, params.min_island_frames)
    pts[~keep] = np.nan

    low = ~(vis >= params.vis_threshold)  # NaN visibility counts as low
    pts[low] = np.nan

    for j in range(pts.shape[1]):
        for c in range(2):
            pts[:, j, c] = _interp_short_gaps(pts[:, j, c], params.max_gap_frames)

    # Body-relative normalisation: centre on hip midpoint, scale by (smoothed) torso length.
    hip = (pts[:, J["l_hip"]] + pts[:, J["r_hip"]]) / 2
    sho = (pts[:, J["l_shoulder"]] + pts[:, J["r_shoulder"]]) / 2
    torso = np.linalg.norm(sho - hip, axis=1)
    torso_s = _nan_median_filter(torso, size=15)
    norm = (pts - hip[:, None, :]) / torso_s[:, None, None]
    return CleanPose(pts=pts, norm=norm)


def _nan_median_filter(x: np.ndarray, size: int) -> np.ndarray:
    """Median filter that ignores NaNs (falls back to the raw value where needed)."""
    valid = ~np.isnan(x)
    if not valid.any():
        return x
    filled = np.where(valid, x, np.interp(np.arange(len(x)), np.flatnonzero(valid), x[valid]))
    out = median_filter(filled, size=size, mode="nearest")
    out[~valid] = np.nan
    return out


def mirror(points: np.ndarray) -> np.ndarray:
    """Mirror (T, J, 2) points: negate x and swap left/right joints.

    Direction vectors are what gets scored, so negating x about any vertical axis is
    equivalent; we negate about 0.
    """
    out = points[:, MIRROR_PERM, :].copy()
    out[..., 0] = -out[..., 0]
    return out
