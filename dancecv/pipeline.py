"""alignment.json -> pose extraction -> normalisation/mirroring -> scoring -> results.json."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from dancecv import debug_viz
from dancecv.config import Params
from dancecv.contract import (
    BODY_PARTS, Frames, Media, MirrorSpan, Mirroring, Results, Segment, Span, load_alignment,
)
from dancecv.normalize import clean
from dancecv.pose import extract_poses
from dancecv.scoring import LIMB_NAMES, score_with_mirroring
from dancecv.segments import find_no_pose, find_segments
from dancecv.video_io import TARGET_FPS, trim_video

Progress = Callable[[str, float], None]


def _nan_to_none(x: np.ndarray, nd: int = 2) -> list:
    return [None if not np.isfinite(v) else round(float(v), nd) for v in x]


def _rel(path: str | Path, base: Path) -> str:
    try:
        return os.path.relpath(Path(path).resolve(), base.resolve())
    except ValueError:  # different drive (Windows)
        return str(Path(path).resolve())


def run_from_alignment(alignment_path: str | Path, out_dir: str | Path | None = None,
                       params: Optional[Params] = None, debug: bool = True,
                       progress: Optional[Progress] = None) -> Results:
    """Score the comparison video against the reference. Writes <out_dir>/results.json."""
    params = params or Params()
    alignment_path = Path(alignment_path)
    out_dir = Path(out_dir) if out_dir else alignment_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    report = progress or (lambda stage, frac: None)

    al = load_alignment(alignment_path)

    # 1. Frame-locked trimmed clips (use the alignment step's if it made them).
    report("trim", 0.0)
    ref_clip, comp_clip = al.reference_trimmed, al.comparison_trimmed
    if not (ref_clip and comp_clip and Path(ref_clip).exists() and Path(comp_clip).exists()):
        ref_clip, comp_clip = str(out_dir / "ref_trimmed.mp4"), str(out_dir / "comp_trimmed.mp4")
        trim_video(al.reference_video, ref_clip, al.overlap_start_ref, al.overlap_duration, TARGET_FPS)
        trim_video(al.comparison_video, comp_clip, al.overlap_start_ref + al.offset_seconds,
                   al.overlap_duration, TARGET_FPS)

    # 2. Pose extraction (cached per file).
    ref_pose = extract_poses(ref_clip, params.model, progress=lambda f: report("pose", 0.5 * f))
    comp_pose = extract_poses(comp_clip, params.model, progress=lambda f: report("pose", 0.5 + 0.5 * f))

    # 3. Pair frames N <-> N; normalise; score both orientations.
    report("scoring", 0.0)
    fps = TARGET_FPS
    T = min(len(ref_pose), len(comp_pose))
    ref_c = clean(ref_pose.kp[:T], params)
    comp_c = clean(comp_pose.kp[:T], params)
    decision = score_with_mirroring(ref_c.pts, comp_c.pts, fps, params)
    s = decision.series

    # 4. Segments.
    segs, smooth = find_segments(s.score, s.part_scores, fps, params)
    no_pose = find_no_pose(s.score, fps, params)

    t0_ref = al.overlap_start_ref
    t0_comp = al.overlap_start_ref + al.offset_seconds
    segments = [
        Segment(
            start=round(g.i0 / fps, 3), end=round(g.i1 / fps, 3),
            start_ref_orig=round(t0_ref + g.i0 / fps, 3), end_ref_orig=round(t0_ref + g.i1 / fps, 3),
            start_comp_orig=round(t0_comp + g.i0 / fps, 3), end_comp_orig=round(t0_comp + g.i1 / fps, 3),
            severity=round(g.severity, 3), severity_label=g.severity_label,
            mean_score=round(g.mean_score, 1), worst_body_parts=g.worst_body_parts,
        )
        for g in segs
    ]

    # 5. Debug artifacts.
    media = Media(reference_trimmed=_rel(ref_clip, out_dir), comparison_trimmed=_rel(comp_clip, out_dir))
    if debug:
        report("debug", 0.0)
        debug_viz.render_debug_video(ref_clip, comp_clip, ref_c.pts, comp_c.pts, s.score, s.lag, segs,
                                     decision.mirrored, fps, out_dir / "debug.mp4")
        media.debug_video = "debug.mp4"
        overall_txt = f"{np.nanmean(s.score):.1f}" if np.isfinite(s.score).any() else "n/a"
        debug_viz.render_timeline(
            s.score, smooth, segs, no_pose, fps, params.flag_threshold,
            f"{Path(al.reference_video).name} vs {Path(al.comparison_video).name}: overall {overall_txt}"
            f"{'  (comp mirrored)' if decision.mirrored else ''}",
            out_dir / "timeline.png")
        debug_viz.render_flagged_strip(ref_clip, comp_clip, ref_c.pts, comp_c.pts, s.score, segs, fps,
                                       out_dir / "flagged_strip.png")

    overall = s.mean()
    results = Results(
        alignment=al,
        media=media,
        fps=fps,
        overall_score=round(overall, 1) if np.isfinite(overall) else None,
        mirrored=Mirroring(global_=decision.mirrored,
                           segments=[MirrorSpan(start=0.0, end=round(T / fps, 3), mirrored=decision.mirrored)]),
        segments=segments,
        no_pose_segments=[Span(start=round(a / fps, 3), end=round(b / fps, 3)) for a, b in no_pose],
        frames=Frames(
            t=[round(i / fps, 4) for i in range(T)],
            score=_nan_to_none(s.score),
            lag_frames=[None if not np.isfinite(v) else int(v) for v in s.lag],
            mirrored=[decision.mirrored] * T,
            part_scores={p: _nan_to_none(s.part_scores[p], 1) for p in BODY_PARTS},
            limb_angle_err_deg={n: _nan_to_none(s.limb_err_deg[:, k], 1) for k, n in enumerate(LIMB_NAMES)},
        ),
        params={**params.to_dict(),
                "mirror_mean_original": round(decision.mean_original, 2),
                "mirror_mean_mirrored": round(decision.mean_mirrored, 2)},
    )
    (out_dir / "results.json").write_text(results.to_json())
    report("done", 1.0)
    return results
