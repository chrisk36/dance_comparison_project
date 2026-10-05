"""Limb-direction similarity, lag tolerance and mirror selection."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dancecv.config import Params
from dancecv.contract import BODY_PARTS
from dancecv.normalize import J, mirror
from dancecv.segments import nan_smooth

# (name, from, to, body part, weight). "mid_*" are virtual joints.
LIMBS: list[tuple[str, str, str, str, float]] = [
    ("l_upper_arm", "l_shoulder", "l_elbow", "left_arm", 1.0),
    ("l_forearm", "l_elbow", "l_wrist", "left_arm", 1.0),
    ("r_upper_arm", "r_shoulder", "r_elbow", "right_arm", 1.0),
    ("r_forearm", "r_elbow", "r_wrist", "right_arm", 1.0),
    ("l_thigh", "l_hip", "l_knee", "left_leg", 1.0),
    ("l_shin", "l_knee", "l_ankle", "left_leg", 1.0),
    ("r_thigh", "r_hip", "r_knee", "right_leg", 1.0),
    ("r_shin", "r_knee", "r_ankle", "right_leg", 1.0),
    ("shoulder_line", "l_shoulder", "r_shoulder", "torso", 0.5),
    ("hip_line", "l_hip", "r_hip", "torso", 0.5),
    ("torso", "mid_hip", "mid_shoulder", "torso", 0.5),
    ("head", "mid_shoulder", "nose", "head", 0.5),
]
LIMB_NAMES = [l[0] for l in LIMBS]
LIMB_WEIGHTS = np.array([l[4] for l in LIMBS])
LIMB_PART = [l[3] for l in LIMBS]


def _joint(pts: np.ndarray, name: str) -> np.ndarray:
    if name == "mid_hip":
        return (pts[:, J["l_hip"]] + pts[:, J["r_hip"]]) / 2
    if name == "mid_shoulder":
        return (pts[:, J["l_shoulder"]] + pts[:, J["r_shoulder"]]) / 2
    return pts[:, J[name]]


def limb_units(pts: np.ndarray) -> np.ndarray:
    """(T, J, 2) points -> (T, L, 2) unit direction vectors (NaN where a joint is missing)."""
    vecs = np.stack([_joint(pts, b) - _joint(pts, a) for _, a, b, _, _ in LIMBS], axis=1)
    n = np.linalg.norm(vecs, axis=2, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 1e-6, vecs / n, np.nan)


def motion_weights(u_ref: np.ndarray, params: Params) -> np.ndarray:
    """Per-limb weights that favour limbs the reference choreography actually moves.

    Static limbs (e.g. legs in an arm-driven TikTok) match in almost any upright pose, so at full
    weight they pull every score towards ~80 and hide real mistakes. Weight = base weight x
    clip(circular spread of the limb's direction in the reference / motion_full_deg, floor, 1).
    """
    if not params.motion_weighting:
        return LIMB_WEIGHTS.copy()
    ang = np.arctan2(u_ref[..., 1], u_ref[..., 0])  # (T, L)
    R = np.abs(np.nanmean(np.exp(1j * ang), axis=0))  # mean resultant length per limb
    with np.errstate(divide="ignore", invalid="ignore"):
        spread = np.degrees(np.sqrt(-2.0 * np.log(np.clip(R, 1e-9, 1.0))))
    spread = np.nan_to_num(spread, nan=params.motion_full_deg)  # never-visible limb: neutral
    return LIMB_WEIGHTS * np.clip(spread / params.motion_full_deg, params.motion_floor, 1.0)


@dataclass
class ScoreSeries:
    score: np.ndarray  # (T,) 0..100, NaN = not scorable
    lag: np.ndarray  # (T,) best lag in frames (NaN where not scorable)
    limb_err_deg: np.ndarray  # (T, L) angle error at the best lag
    part_scores: dict[str, np.ndarray]  # part -> (T,) 0..100
    limb_weights: np.ndarray  # (L,) weights used for the frame score

    def mean(self) -> float:
        return float(np.nanmean(self.score)) if np.isfinite(self.score).any() else float("nan")


def score_series(ref_pts: np.ndarray, comp_pts: np.ndarray, fps: float, params: Params) -> ScoreSeries:
    """Score ref frame t against comp frame t+k, k within +-lag_window_s.

    The lag is chosen per frame as the one that scores best over a +-lag_context_s/2
    neighbourhood, so the comp dancer may run slightly early/late without penalty.
    """
    T = min(len(ref_pts), len(comp_pts))
    u_ref = limb_units(ref_pts[:T])
    u_comp = limb_units(comp_pts[:T])
    W = int(round(params.lag_window_s * fps))
    L = len(LIMBS)
    theta_free = np.deg2rad(params.theta_free_deg)
    theta_max = np.deg2rad(params.theta_max_deg)
    total_w = LIMB_WEIGHTS.sum()
    weights = motion_weights(u_ref, params)

    lags = np.arange(-W, W + 1)
    K = len(lags)
    frame_k = np.full((K, T), np.nan)  # frame score if comp is matched at lag k
    err_k = np.full((K, T, L), np.nan)
    limb_s_k = np.full((K, T, L), np.nan)

    for ki, k in enumerate(lags):
        # comp frame index = t + k
        lo, hi = max(0, -k), min(T, T - k)
        if hi <= lo:
            continue
        a = u_ref[lo:hi]
        b = u_comp[lo + k:hi + k]
        cos = np.clip(np.sum(a * b, axis=2), -1.0, 1.0)  # NaN propagates
        err = np.arccos(cos)  # (n, L) radians
        limb_s = np.clip(1.0 - (err - theta_free) / (theta_max - theta_free), 0.0, 1.0)
        valid = ~np.isnan(limb_s)
        # Scorable = enough of the body visible (base weights); average with motion weights.
        enough = np.where(valid, LIMB_WEIGHTS, 0.0).sum(axis=1) >= params.min_valid_weight_frac * total_w
        w = np.where(valid, weights, 0.0)
        frame_k[ki, lo:hi] = np.where(
            enough,
            100.0 * np.sum(np.where(valid, limb_s, 0.0) * w, axis=1) / np.maximum(w.sum(axis=1), 1e-9),
            np.nan,
        )
        err_k[ki, lo:hi] = np.rad2deg(err)
        limb_s_k[ki, lo:hi] = limb_s

    # Pick the lag that is best over a short neighbourhood, not per frame: a wrong timing can
    # match a single frame by luck, but rarely a whole stretch of movement at one lag.
    C = max(1, int(round(params.lag_context_s * fps)))
    ctx = np.stack([nan_smooth(f, C) for f in frame_k])
    ctx = np.where(np.isfinite(frame_k), ctx - 1e-6 * np.abs(lags)[:, None], -np.inf)  # ties -> small |k|
    has = np.isfinite(ctx).any(axis=0)
    kbest = np.argmax(ctx, axis=0)
    t_idx = np.arange(T)
    score = np.where(has, frame_k[kbest, t_idx], np.nan)
    best_lag = np.where(has, lags[kbest].astype(float), np.nan)
    best_err = np.where(has[:, None], err_k[kbest, t_idx], np.nan)
    best_limb_s = np.where(has[:, None], limb_s_k[kbest, t_idx], np.nan)
    part_scores = {}
    for part in BODY_PARTS:
        cols = [i for i, p in enumerate(LIMB_PART) if p == part]
        s = best_limb_s[:, cols]
        w = np.where(~np.isnan(s), LIMB_WEIGHTS[cols], 0.0)
        with np.errstate(invalid="ignore"):
            part_scores[part] = 100.0 * np.nansum(np.nan_to_num(s) * w, axis=1) / w.sum(axis=1)
    return ScoreSeries(score=score, lag=best_lag, limb_err_deg=best_err, part_scores=part_scores,
                       limb_weights=weights)


@dataclass
class MirrorDecision:
    mirrored: bool
    series: ScoreSeries
    mean_original: float
    mean_mirrored: float


def score_with_mirroring(ref_pts: np.ndarray, comp_pts: np.ndarray, fps: float,
                         params: Params) -> MirrorDecision:
    """Score both orientations of the comparison dancer and keep the better one (global)."""
    orig = score_series(ref_pts, comp_pts, fps, params)
    mirr = score_series(ref_pts, mirror(comp_pts), fps, params)
    both = np.isfinite(orig.score) & np.isfinite(mirr.score)
    m_o = float(np.mean(orig.score[both])) if both.any() else float("nan")
    m_m = float(np.mean(mirr.score[both])) if both.any() else float("nan")
    use_mirror = bool(np.isfinite(m_m) and m_m > m_o + params.mirror_margin)
    return MirrorDecision(mirrored=use_mirror, series=mirr if use_mirror else orig,
                          mean_original=m_o, mean_mirrored=m_m)
