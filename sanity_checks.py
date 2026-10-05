"""Sanity checks for the scoring pipeline (also used to tune thresholds).

  1. ref vs itself                        -> ~100, no segments
  2. ref vs horizontally flipped ref      -> ~100, mirroring detected, ~no segments
  3. ref vs comp (audio xcorr alignment)  -> believable score / timestamps
  4. ref vs itself at wrong offsets       -> low scores, mostly flagged (negative controls)

Usage: python sanity_checks.py [--ref test_videos/ref.mp4] [--comp test_videos/comp.mp4] [--debug]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from dancecv.alignment.stub import align
from dancecv.config import REPO_ROOT, Params
from dancecv.pipeline import run_from_alignment
from dancecv.video_io import hflip_video

NEG_OFFSETS = (0.7, 1.5, 3.0)


def pct_flagged(results) -> float:
    scored = [i for i, s in enumerate(results.frames.score) if s is not None]
    if not scored:
        return float("nan")
    fps = results.fps
    flagged = set()
    for seg in results.segments:
        flagged.update(range(int(round(seg.start * fps)), int(round(seg.end * fps))))
    return 100.0 * len(flagged.intersection(scored)) / len(scored)


def run_case(name: str, ref: Path, comp: Path, out: Path, params: Params, debug: bool,
             method: str = "zero", offset: float | None = None):
    align(ref, comp, out, trim=True, method=method, offset=offset)
    r = run_from_alignment(out / "alignment.json", out, params, debug=debug)
    lags = [v for v in r.frames.lag_frames if v is not None]
    return {
        "check": name,
        "offset": r.alignment.offset_seconds,
        "score": r.overall_score,
        "flagged_pct": pct_flagged(r),
        "segments": len(r.segments),
        "mirrored": r.mirrored.global_,
        "median_lag": float(np.median(lags)) if lags else float("nan"),
        "scored_frames": sum(s is not None for s in r.frames.score),
    }


def run_all(ref: Path, comp: Path, params: Params, debug: bool, out_root: Path) -> list[dict]:
    flipped = out_root / "ref_flipped.mp4"
    if not flipped.exists():
        out_root.mkdir(parents=True, exist_ok=True)
        hflip_video(ref, flipped)
    rows = [
        run_case("1 ref vs ref", ref, ref, out_root / "1_self", params, debug),
        run_case("2 ref vs flipped", ref, flipped, out_root / "2_flipped", params, debug),
        run_case("3 ref vs comp", ref, comp, out_root / "3_ref_vs_comp", params, debug, method="xcorr"),
    ]
    for off in NEG_OFFSETS:
        rows.append(run_case(f"4 neg ctrl {off}s", ref, ref, out_root / f"4_neg_{off}", params, False,
                             offset=off))
    return rows


def print_table(rows: list[dict]) -> None:
    print(f"\n{'check':22s} {'offset':>7s} {'score':>6s} {'flag%':>6s} {'segs':>5s} {'mirr':>5s} "
          f"{'lag':>5s} {'frames':>6s}")
    for r in rows:
        score = f"{r['score']:6.1f}" if r["score"] is not None else "   n/a"
        print(f"{r['check']:22s} {r['offset']:+7.3f} {score} {r['flagged_pct']:6.1f} {r['segments']:5d} "
              f"{str(r['mirrored']):>5s} {r['median_lag']:+5.1f} {r['scored_frames']:6d}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="test_videos/ref.mp4")
    ap.add_argument("--comp", default="test_videos/comp.mp4")
    ap.add_argument("--debug", action="store_true", help="also write debug videos/images for checks 1-3")
    args = ap.parse_args()
    rows = run_all(Path(args.ref), Path(args.comp), Params(), args.debug, REPO_ROOT / "outputs" / "sanity")
    print_table(rows)


if __name__ == "__main__":
    main()
