"""Stand-in for Wei's alignment step. Produces alignment.json in the agreed format.

Two modes:
  * offset 0 (default) or a fixed --offset, for plumbing/dev work
  * --xcorr: quick audio cross-correlation of onset envelopes, so real test pairs line up

Wei's real implementation lives in dancecv/alignment/audio.py and exposes the same
`align(ref_path, comp_path, out_dir, trim=True) -> Alignment` signature.

Usage:
  python -m dancecv.alignment.stub REF COMP --out DIR [--xcorr | --offset X] [--no-trim]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
from scipy import signal

from dancecv.contract import Alignment, save_alignment
from dancecv.video_io import TARGET_FPS, decode_audio_mono, probe, trim_video

SR = 22050
HOP_S = 0.010  # 10 ms onset-envelope resolution
PEAK_EXCLUSION_S = 0.5  # music repeats every beat: ignore near-peak lags when judging confidence
MIN_OVERLAP_FRAC = 0.5  # only consider lags where the clips overlap by >= 50% of the shorter one


def onset_envelope(audio: np.ndarray, sr: int = SR, hop_s: float = HOP_S) -> np.ndarray:
    """Spectral-flux onset strength, high-passed and standardized."""
    hop = int(round(sr * hop_s))
    n_fft = 2048
    _, _, Z = signal.stft(audio, fs=sr, nperseg=n_fft, noverlap=n_fft - hop, boundary=None, padded=False)
    logmag = np.log1p(100.0 * np.abs(Z))
    flux = np.maximum(np.diff(logmag, axis=1), 0.0).sum(axis=0)
    # Remove slow loudness trends (~1 s moving average) so the beat structure dominates.
    win = max(1, int(round(1.0 / hop_s)))
    flux = flux - np.convolve(flux, np.ones(win) / win, mode="same")
    flux = np.maximum(flux, 0.0)
    return (flux - flux.mean()) / (flux.std() + 1e-9)


def estimate_offset(ref_path: str, comp_path: str) -> tuple[float, float, dict]:
    """Return (offset_seconds, confidence, debug) with comp_time = ref_time + offset."""
    env_ref = onset_envelope(decode_audio_mono(ref_path, SR))
    env_comp = onset_envelope(decode_audio_mono(comp_path, SR))

    # corr[k] = sum_n comp[n + lag_k] * ref[n]  -> the peak lag is the offset in hops.
    corr = signal.correlate(env_comp, env_ref, mode="full", method="fft")
    lags = signal.correlation_lags(len(env_comp), len(env_ref), mode="full")

    # Normalize by overlap length (unbiased) and drop lags with too little overlap.
    overlap = np.minimum(len(env_ref), len(env_comp) - lags) - np.maximum(0, -lags)
    overlap = np.clip(overlap, 0, None)
    valid = overlap >= MIN_OVERLAP_FRAC * min(len(env_ref), len(env_comp))
    score = np.full_like(corr, -np.inf, dtype=float)
    score[valid] = corr[valid] / overlap[valid]

    best = int(np.argmax(score))
    p1 = float(score[best])

    # Sub-hop refinement with a parabola through the peak and its neighbours.
    frac = 0.0
    if 0 < best < len(score) - 1 and np.isfinite(score[best - 1]) and np.isfinite(score[best + 1]):
        a, b, c = score[best - 1], score[best], score[best + 1]
        denom = a - 2 * b + c
        if denom != 0:
            frac = float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
    offset = (lags[best] + frac) * HOP_S

    # Confidence: how much of the remaining headroom (scores are ~normalized correlations, max ~1)
    # the top peak claims over the best peak at least 0.5 s away. Dance music repeats every
    # bar, so runner-up peaks are often high; p1/p2-style ratios understate a clear win.
    excl = int(round(PEAK_EXCLUSION_S / HOP_S))
    far = score.copy()
    far[max(0, best - excl): best + excl + 1] = -np.inf
    p2 = float(np.max(far)) if np.isfinite(far).any() else 0.0
    p2c = float(np.clip(p2, 0.0, 0.999))
    confidence = float(np.clip((p1 - p2c) / (1.0 - p2c), 0.0, 1.0)) if p1 > 0 else 0.0

    return float(offset), confidence, {"peak": p1, "second_peak": p2, "lag_hops": int(lags[best])}


def align(ref_path: str | Path, comp_path: str | Path, out_dir: str | Path, trim: bool = True,
          method: str = "zero", offset: float | None = None) -> Alignment:
    """Write <out_dir>/alignment.json (plus trimmed clips if trim) and return it.

    method: "zero" (offset 0, or `offset` if given) or "xcorr" (audio cross-correlation).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ref_path, comp_path = Path(ref_path).resolve(), Path(comp_path).resolve()
    ref_info, comp_info = probe(ref_path), probe(comp_path)

    confidence = 1.0
    if method == "xcorr":
        if not (ref_info.has_audio and comp_info.has_audio):
            raise ValueError("xcorr alignment needs an audio track in both videos")
        offset, confidence, dbg = estimate_offset(str(ref_path), str(comp_path))
        print(f"[align] xcorr offset={offset:+.3f}s confidence={confidence:.2f} "
              f"(peak={dbg['peak']:.3f}, next peak >0.5s away={dbg['second_peak']:.3f})")
    elif method == "zero":
        offset = float(offset or 0.0)
    else:
        raise ValueError(f"unknown method {method!r}")

    start = max(0.0, -offset)
    end = min(ref_info.duration, comp_info.duration - offset)
    if end - start <= 0:
        raise ValueError(f"videos do not overlap with offset {offset:+.3f}s")

    def rel(p: Path) -> str:
        return os.path.relpath(p, out_dir.resolve())

    alignment = Alignment(
        reference_video=rel(ref_path),
        comparison_video=rel(comp_path),
        offset_seconds=round(offset, 4),
        overlap_start_ref=round(start, 4),
        overlap_end_ref=round(end, 4),
        reference_fps=round(ref_info.fps, 3),
        comparison_fps=round(comp_info.fps, 3),
        alignment_confidence=round(confidence, 3),
    )

    if trim:
        dur = end - start
        ref_trim, comp_trim = out_dir / "ref_trimmed.mp4", out_dir / "comp_trimmed.mp4"
        trim_video(ref_path, ref_trim, start, dur, TARGET_FPS)
        trim_video(comp_path, comp_trim, start + offset, dur, TARGET_FPS)
        alignment.reference_trimmed = ref_trim.name
        alignment.comparison_trimmed = comp_trim.name

    save_alignment(alignment, out_dir / "alignment.json")
    return alignment


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference")
    ap.add_argument("comparison")
    ap.add_argument("--out", required=True, help="output directory for alignment.json and trimmed clips")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--xcorr", action="store_true", help="estimate the offset by audio cross-correlation")
    g.add_argument("--offset", type=float, default=None, help="force a fixed offset in seconds")
    ap.add_argument("--no-trim", action="store_true", help="skip writing trimmed 30 fps clips")
    args = ap.parse_args()

    a = align(args.reference, args.comparison, args.out, trim=not args.no_trim,
              method="xcorr" if args.xcorr else "zero", offset=args.offset)
    print(a.model_dump_json(indent=2, exclude_none=True))


if __name__ == "__main__":
    main()
