"""Turn per-frame scores into out-of-sync segments and no-pose spans."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dancecv.config import Params
from dancecv.contract import BODY_PARTS


@dataclass
class RawSegment:
    i0: int  # first frame (inclusive)
    i1: int  # last frame (exclusive)
    mean_score: float
    severity: float
    severity_label: str
    worst_body_parts: list[str]


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index pairs of consecutive True values."""
    m = np.concatenate([[False], mask.astype(bool), [False]])
    d = np.diff(m.astype(int))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def merge_runs(rs: list[tuple[int, int]], max_gap: int) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in rs:
        if out and a - out[-1][1] <= max_gap:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def nan_smooth(x: np.ndarray, win: int) -> np.ndarray:
    """Centred moving average that ignores NaNs; stays NaN where the input is NaN."""
    if win <= 1:
        return x.copy()
    valid = np.isfinite(x)
    k = np.ones(win)
    num = np.convolve(np.where(valid, x, 0.0), k, mode="same")
    den = np.convolve(valid.astype(float), k, mode="same")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[~valid] = np.nan
    return out


def severity_label(sev: float) -> str:
    return "low" if sev < 0.15 else "medium" if sev < 0.35 else "high"


def find_segments(score: np.ndarray, part_scores: dict[str, np.ndarray], fps: float,
                  params: Params) -> tuple[list[RawSegment], np.ndarray]:
    """Return (segments, smoothed score)."""
    smooth = nan_smooth(score, max(1, int(round(params.smooth_s * fps))))
    below = np.isfinite(smooth) & (smooth < params.flag_threshold)
    rs = merge_runs(runs(below), int(round(params.merge_gap_s * fps)))
    min_len = int(round(params.min_segment_s * fps))

    segs = []
    for a, b in rs:
        if b - a < min_len:
            continue
        mean = float(np.nanmean(score[a:b]))
        sev = float(np.clip((params.flag_threshold - mean) / params.flag_threshold, 0.0, 1.0))
        part_means = {p: float(np.nanmean(part_scores[p][a:b])) for p in BODY_PARTS
                      if np.isfinite(part_scores[p][a:b]).any()}
        ranked = sorted(part_means, key=part_means.get)
        worst = [p for p in ranked if part_means[p] < params.flag_threshold][:2] or ranked[:1]
        segs.append(RawSegment(a, b, mean, sev, severity_label(sev), worst))
    return segs, smooth


def find_no_pose(score: np.ndarray, fps: float, params: Params) -> list[tuple[int, int]]:
    rs = merge_runs(runs(~np.isfinite(score)), int(round(params.merge_gap_s * fps)))
    return [(a, b) for a, b in rs if (b - a) >= params.min_no_pose_s * fps]
