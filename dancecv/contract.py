"""Data contracts shared between the alignment step (Wei), scoring (Christian) and the UI.

CONTRACT.md is the human-readable version of this file; keep the two in sync.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------------------
# alignment.json  (output of Wei's step, input to pose/scoring)
# --------------------------------------------------------------------------------------
class Alignment(BaseModel):
    """Timing alignment of a comparison video against a reference video.

    Convention: comparison_time = reference_time + offset_seconds.
    Video paths are absolute, or relative to the directory containing alignment.json.
    """

    model_config = ConfigDict(extra="allow")  # Wei may add extra debug fields

    reference_video: str
    comparison_video: str
    offset_seconds: float
    overlap_start_ref: float
    overlap_end_ref: float
    reference_fps: float
    comparison_fps: float
    alignment_confidence: float = Field(ge=0.0, le=1.0)

    # Optional: clips cut to the overlap and re-encoded at 30 fps, so frame N == frame N.
    reference_trimmed: Optional[str] = None
    comparison_trimmed: Optional[str] = None

    @property
    def overlap_duration(self) -> float:
        return self.overlap_end_ref - self.overlap_start_ref

    def resolved(self, base_dir: Path) -> "Alignment":
        """Copy with every path made absolute relative to base_dir."""

        def fix(p: Optional[str]) -> Optional[str]:
            if p is None:
                return None
            pp = Path(p)
            return str(pp if pp.is_absolute() else (base_dir / pp).resolve())

        return self.model_copy(
            update={
                "reference_video": fix(self.reference_video),
                "comparison_video": fix(self.comparison_video),
                "reference_trimmed": fix(self.reference_trimmed),
                "comparison_trimmed": fix(self.comparison_trimmed),
            }
        )


def load_alignment(path: str | Path) -> Alignment:
    """Load alignment.json and resolve its paths to absolute paths."""
    path = Path(path)
    data = json.loads(path.read_text())
    return Alignment.model_validate(data).resolved(path.parent.resolve())


def save_alignment(alignment: Alignment, path: str | Path) -> None:
    Path(path).write_text(alignment.model_dump_json(indent=2, exclude_none=True))


# --------------------------------------------------------------------------------------
# results.json  (output of pose/scoring, input to the UI)
# All primary times are in trimmed-clip seconds (0 = overlap start).
# --------------------------------------------------------------------------------------
BodyPart = Literal["left_arm", "right_arm", "left_leg", "right_leg", "torso", "head"]
BODY_PARTS: tuple[str, ...] = ("left_arm", "right_arm", "left_leg", "right_leg", "torso", "head")


class Segment(BaseModel):
    start: float  # trimmed-clip seconds
    end: float
    start_ref_orig: float  # seconds in the original reference video
    end_ref_orig: float
    start_comp_orig: float  # seconds in the original comparison video
    end_comp_orig: float
    severity: float  # 0..1, higher = worse
    severity_label: Literal["low", "medium", "high"]
    mean_score: float  # 0..100
    worst_body_parts: list[BodyPart]


class Span(BaseModel):
    start: float
    end: float


class MirrorSpan(Span):
    mirrored: bool


class Mirroring(BaseModel):
    global_: bool = Field(alias="global")
    segments: list[MirrorSpan]

    model_config = ConfigDict(populate_by_name=True)


class Media(BaseModel):
    reference_trimmed: str
    comparison_trimmed: str
    debug_video: Optional[str] = None


class Frames(BaseModel):
    t: list[float]  # trimmed-clip seconds, one entry per scored frame
    score: list[Optional[float]]  # 0..100, null where no valid pose
    lag_frames: list[Optional[int]]  # best comp lag within the tolerance window (+ = comp late)
    mirrored: list[bool]
    part_scores: dict[str, list[Optional[float]]]  # body part -> 0..100 per frame
    limb_angle_err_deg: dict[str, list[Optional[float]]]  # limb -> angle error per frame


class Results(BaseModel):
    schema_version: int = 1
    alignment: Alignment
    media: Media
    fps: float
    overall_score: Optional[float]  # 0..100, null if nothing could be scored
    mirrored: Mirroring
    segments: list[Segment]
    no_pose_segments: list[Span]
    frames: Frames
    params: dict

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, by_alias=True)
