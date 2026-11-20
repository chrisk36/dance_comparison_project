import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, "/tmp/ds")
from dancecv.alignment.stub import align
from dancecv.config import Params
from dancecv.pipeline import run_from_alignment
from dancecv.video_io import hflip_video
from sanity_checks import pct_flagged

D = Path("/Users/natalielim/Documents/cis 5810/dance_comparison_project/backend/data")
ref = D / "5ab684fe649e47e794c479af5791fa3c/reference.mp4"
R = Path("/tmp/dsabl")
flipped = R / "ref_flipped.mp4"
if not flipped.exists():
    hflip_video(ref, flipped)

pairs = {}
pairs["cover (audio-aligned)"] = Path("/tmp/dsruns/cover/alignment.json")
pairs["low-confidence align"] = Path("/tmp/dsruns/lowconf/alignment.json")
for name, comp, off in [("ref vs itself", ref, 0.0), ("ref vs mirrored ref", flipped, 0.0),
                        ("ref vs itself +0.1s", ref, 0.1), ("ref vs itself +0.7s", ref, 0.7),
                        ("ref vs itself +1.5s", ref, 1.5)]:
    out = R / name.replace(" ", "_")
    align(ref, comp, out, trim=True, method="zero", offset=off)
    pairs[name] = out / "alignment.json"

NOMIR = 1e9
configs = {
    "B0 baseline":        Params(mirror_margin=NOMIR, lag_window_s=0.0, motion_weighting=False),
    "I1 +mirror":         Params(lag_window_s=0.0, motion_weighting=False),
    "I2 +lag tolerance":  Params(motion_weighting=False),
    "I3 +motion weights": Params(),
}
rows = []
for pname, ap in pairs.items():
    for cname, p in configs.items():
        out = R / "runs" / (pname.replace(" ", "_") + "__" + cname.split()[0])
        r = run_from_alignment(ap, out, p, debug=False)
        lags = [v for v in r.frames.lag_frames if v is not None]
        parts = {}
        rows.append(dict(pair=pname, config=cname, score=r.overall_score, segs=len(r.segments),
                         flag=round(pct_flagged(r), 1), mirrored=r.mirrored.global_,
                         lag_med_s=round(float(np.median(lags)) / r.fps, 3) if lags else None,
                         worst=[s.worst_body_parts for s in r.segments][:6]))
        print(rows[-1], flush=True)
json.dump(rows, open(R / "ablation.json", "w"), indent=1)
