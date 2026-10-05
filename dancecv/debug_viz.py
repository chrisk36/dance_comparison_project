"""Debug artifacts: side-by-side skeleton video, score timeline, flagged-frame strip."""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

from dancecv.normalize import J
from dancecv.segments import RawSegment

EDGES = [
    ("l_shoulder", "r_shoulder"), ("l_hip", "r_hip"),
    ("l_shoulder", "l_hip"), ("r_shoulder", "r_hip"),
    ("l_shoulder", "l_elbow"), ("l_elbow", "l_wrist"),
    ("r_shoulder", "r_elbow"), ("r_elbow", "r_wrist"),
    ("l_hip", "l_knee"), ("l_knee", "l_ankle"),
    ("r_hip", "r_knee"), ("r_knee", "r_ankle"),
]
LEFT, RIGHT, CENTER = (255, 160, 0), (0, 140, 255), (230, 230, 230)  # BGR: left blue, right orange
PANEL_H = 720
HEADER_H = 64


def score_color(score: float | None) -> tuple[int, int, int]:
    if score is None or not np.isfinite(score):
        return (128, 128, 128)
    if score >= 80:
        return (80, 190, 60)
    if score >= 65:
        return (0, 190, 240)
    return (60, 60, 230)


def draw_skeleton(img: np.ndarray, pts: np.ndarray) -> None:
    """pts: (J, 2) pixel coords in img's frame (NaN = missing)."""
    def p(name):
        x, y = pts[J[name]]
        return None if np.isnan(x) or np.isnan(y) else (int(x), int(y))

    for a, b in EDGES:
        pa, pb = p(a), p(b)
        if pa and pb:
            col = LEFT if a.startswith("l_") and b.startswith("l_") else \
                RIGHT if a.startswith("r_") and b.startswith("r_") else CENTER
            cv2.line(img, pa, pb, col, 4, cv2.LINE_AA)
    for name in J:
        pt = p(name)
        if pt:
            col = LEFT if name.startswith("l_") else RIGHT if name.startswith("r_") else CENTER
            cv2.circle(img, pt, 6, col, -1, cv2.LINE_AA)


def _panel(frame: np.ndarray | None, pts: np.ndarray | None, size: tuple[int, int]) -> np.ndarray:
    w, h = size
    if frame is None:
        return np.zeros((h, w, 3), np.uint8)
    img = frame.copy()
    if pts is not None:
        draw_skeleton(img, pts)
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def _panel_size(cap: cv2.VideoCapture, height: int) -> tuple[int, int]:
    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    pw = int(round(w * height / h / 2)) * 2
    return pw, height


def render_debug_video(ref_video: str, comp_video: str, ref_pts: np.ndarray, comp_pts: np.ndarray,
                       score: np.ndarray, lag: np.ndarray, segments: list[RawSegment],
                       mirrored: bool, fps: float, out_path: str | Path) -> None:
    cap_r, cap_c = cv2.VideoCapture(ref_video), cv2.VideoCapture(comp_video)
    sr, sc = _panel_size(cap_r, PANEL_H), _panel_size(cap_c, PANEL_H)
    W, H = sr[0] + sc[0], PANEL_H + HEADER_H
    flagged = np.zeros(len(score), bool)
    for s in segments:
        flagged[s.i0:s.i1] = True

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "-",
        "-i", str(ref_video), "-map", "0:v", "-map", "1:a?", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(len(score)):
            ok_r, fr = cap_r.read()
            ok_c, fc = cap_c.read()
            if not (ok_r and ok_c):
                break
            canvas = np.zeros((H, W, 3), np.uint8)
            canvas[HEADER_H:, :sr[0]] = _panel(fr, ref_pts[i], sr)
            canvas[HEADER_H:, sr[0]:] = _panel(fc, comp_pts[i], sc)

            s = score[i]
            col = score_color(s)
            cv2.rectangle(canvas, (0, 0), (W, HEADER_H), col, -1)
            lag_txt = f"lag {int(lag[i]):+d}f" if np.isfinite(lag[i]) else ""
            s_txt = f"{s:5.1f}" if np.isfinite(s) else "  -- "
            txt = f"t={i / fps:5.2f}s  score {s_txt}  {lag_txt}"
            cv2.putText(canvas, txt, (12, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
            tags = (["OUT OF SYNC"] if flagged[i] else []) + (["COMP MIRRORED"] if mirrored else [])
            if tags:
                t2 = "  ".join(tags)
                (tw, _), _ = cv2.getTextSize(t2, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                cv2.putText(canvas, t2, (W - tw - 12, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
            if flagged[i]:
                cv2.rectangle(canvas, (0, HEADER_H), (W - 1, H - 1), (0, 0, 255), 8)
            cv2.putText(canvas, "REF", (12, HEADER_H + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            cv2.putText(canvas, "COMP", (sr[0] + 12, HEADER_H + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            proc.stdin.write(canvas.tobytes())
    finally:
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        proc.wait()
        cap_r.release()
        cap_c.release()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed writing debug video:\n{err[-2000:]}")


def render_timeline(score: np.ndarray, smooth: np.ndarray, segments: list[RawSegment],
                    no_pose: list[tuple[int, int]], fps: float, threshold: float,
                    title: str, out_path: str | Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = np.arange(len(score)) / fps
    fig, ax = plt.subplots(figsize=(12, 3.2), dpi=110)
    for a, b in no_pose:
        ax.axvspan(a / fps, b / fps, color="0.85", lw=0, label="no pose" if a == no_pose[0][0] else None)
    for k, s in enumerate(segments):
        ax.axvspan(s.i0 / fps, s.i1 / fps, color="#e45756", alpha=0.25, lw=0,
                   label="out of sync" if k == 0 else None)
    ax.plot(t, score, color="0.6", lw=0.8, label="frame score")
    ax.plot(t, smooth, color="#1f5fa8", lw=1.6, label="smoothed")
    ax.axhline(threshold, color="#e45756", ls="--", lw=1, label=f"threshold {threshold:g}")
    ax.set_ylim(0, 102)
    ax.set_xlim(0, t[-1] if len(t) else 1)
    ax.set_xlabel("trimmed-clip time (s)")
    ax.set_ylabel("score")
    ax.set_title(title, fontsize=10)
    ax.legend(loc="lower left", fontsize=8, ncol=5, frameon=False)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _grab(cap: cv2.VideoCapture, i: int) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_FRAMES, i)
    ok, f = cap.read()
    return f if ok else None


def render_flagged_strip(ref_video: str, comp_video: str, ref_pts: np.ndarray, comp_pts: np.ndarray,
                         score: np.ndarray, segments: list[RawSegment], fps: float,
                         out_path: str | Path, max_items: int = 8, height: int = 360) -> bool:
    """One tile per segment (worst frame), ref|comp side by side. Returns False if nothing to draw."""
    if not segments:
        return False
    chosen = sorted(sorted(segments, key=lambda s: -s.severity)[:max_items], key=lambda s: s.i0)
    cap_r, cap_c = cv2.VideoCapture(ref_video), cv2.VideoCapture(comp_video)
    sr, sc = _panel_size(cap_r, height), _panel_size(cap_c, height)
    tiles = []
    for s in chosen:
        seg_scores = np.where(np.isfinite(score[s.i0:s.i1]), score[s.i0:s.i1], np.inf)
        i = s.i0 + int(np.argmin(seg_scores))
        tile = np.hstack([_panel(_grab(cap_r, i), ref_pts[i], sr), _panel(_grab(cap_c, i), comp_pts[i], sc)])
        cap = np.full((48, tile.shape[1], 3), 255, np.uint8)
        cv2.putText(cap, f"{s.i0 / fps:.1f}-{s.i1 / fps:.1f}s  worst {score[i]:.0f}",
                    (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(cap, ", ".join(s.worst_body_parts), (6, 41), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (40, 40, 200), 1, cv2.LINE_AA)
        tiles.append(np.vstack([cap, tile]))
    cap_r.release()
    cap_c.release()
    per_row = 4
    rows = []
    for r in range(0, len(tiles), per_row):
        row = tiles[r:r + per_row]
        row += [np.full_like(tiles[0], 255)] * (per_row - len(row)) if len(tiles) > per_row else []
        rows.append(np.hstack([np.pad(t, ((0, 0), (0, 8), (0, 0)), constant_values=255) for t in row]))
    cv2.imwrite(str(out_path), np.vstack(rows))
    return True
