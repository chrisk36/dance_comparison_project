"""End-to-end CLI: alignment (stub) -> pose extraction -> scoring -> results.json + debug artifacts.

Examples:
  python run_pipeline.py test_videos/ref.mp4 test_videos/comp.mp4            # audio xcorr alignment
  python run_pipeline.py test_videos/ref.mp4 test_videos/comp.mp4 --offset 0 # offset-0 stub
  python run_pipeline.py --alignment path/to/alignment.json                  # use Wei's alignment
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from dancecv.alignment.stub import align
from dancecv.config import REPO_ROOT, Params
from dancecv.pipeline import run_from_alignment


def summarize(results, out_dir: Path) -> None:
    a = results.alignment
    print(f"\n== {Path(a.reference_video).name} vs {Path(a.comparison_video).name}")
    print(f"offset {a.offset_seconds:+.3f}s (confidence {a.alignment_confidence:.2f}), "
          f"overlap {a.overlap_duration:.2f}s")
    print(f"overall score: {results.overall_score}   comp mirrored: {results.mirrored.global_}")
    print(f"out-of-sync segments ({len(results.segments)}):")
    for s in results.segments:
        print(f"  {s.start:6.2f}-{s.end:6.2f}s  [{s.severity_label:6s}] mean {s.mean_score:5.1f}  "
              f"{', '.join(s.worst_body_parts)}")
    if results.no_pose_segments:
        print("no pose: " + ", ".join(f"{s.start:.2f}-{s.end:.2f}s" for s in results.no_pose_segments))
    print(f"results: {out_dir / 'results.json'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference", nargs="?")
    ap.add_argument("comparison", nargs="?")
    ap.add_argument("--alignment", help="existing alignment.json (skips the alignment stub)")
    ap.add_argument("--offset", type=float, default=None,
                    help="force a fixed offset (seconds) instead of audio cross-correlation")
    ap.add_argument("--out", help="output directory (default outputs/runs/<ref>_vs_<comp>)")
    ap.add_argument("--model", default="full", choices=["full", "heavy"])
    ap.add_argument("--no-debug", action="store_true", help="skip debug video/images")
    args = ap.parse_args()

    params = Params(model=args.model)
    t0 = time.time()
    if args.alignment:
        alignment_path = Path(args.alignment)
        out_dir = Path(args.out) if args.out else alignment_path.parent
    else:
        if not (args.reference and args.comparison):
            ap.error("give REFERENCE and COMPARISON videos, or --alignment")
        name = f"{Path(args.reference).stem}_vs_{Path(args.comparison).stem}"
        out_dir = Path(args.out) if args.out else REPO_ROOT / "outputs" / "runs" / name
        method = "zero" if args.offset is not None else "xcorr"
        align(args.reference, args.comparison, out_dir, trim=True, method=method, offset=args.offset)
        alignment_path = out_dir / "alignment.json"

    last = {"stage": None}

    def progress(stage: str, frac: float) -> None:
        if stage != last["stage"]:
            print(f"[{time.time() - t0:5.1f}s] {stage}")
            last["stage"] = stage

    results = run_from_alignment(alignment_path, out_dir, params, debug=not args.no_debug, progress=progress)
    summarize(results, out_dir)
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
