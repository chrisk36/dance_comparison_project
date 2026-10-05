"""All tunable parameters in one place. Values are recorded in results.json under "params"."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "models"
CACHE_DIR = REPO_ROOT / "outputs" / "cache"


@dataclass
class Params:
    # pose
    model: str = "full"  # "full" | "heavy"
    vis_threshold: float = 0.5  # joints below this visibility are treated as missing
    max_gap_frames: int = 5  # interpolate missing joints across gaps up to this long
    min_island_frames: int = 6  # drop isolated detections shorter than this (e.g. on end cards)

    # scoring
    theta_free_deg: float = 15.0  # limb angle error tolerated for free (keypoint noise, body proportions)
    theta_max_deg: float = 45.0  # limb angle error that scores 0
    motion_weighting: bool = True  # weight limbs by how much they move in the reference
    motion_full_deg: float = 45.0  # direction spread at which a limb gets full weight
    motion_floor: float = 0.25  # minimum weight factor for (near-)static limbs
    lag_window_s: float = 0.2  # comp may be this early/late without penalty
    mirror_margin: float = 3.0  # mirrored must beat original by this many points to be chosen
    lag_context_s: float = 0.5  # the lag must hold over a neighbourhood this long (local DTW-lite)
    min_valid_weight_frac: float = 0.5  # frame is scored only if this share of limb weight is visible

    # segments
    flag_threshold: float = 60.0  # smoothed frame score below this = out of sync
    smooth_s: float = 0.2
    min_segment_s: float = 0.3
    merge_gap_s: float = 0.2
    min_no_pose_s: float = 0.5

    def to_dict(self) -> dict:
        return asdict(self)
