"""Scan chapters for repetition artifacts and cut a calibration set.

Picks clips spread across score bands so a listener can say where the
artifact actually starts, instead of the threshold being guessed.
"""
import os, sys, json, glob
import numpy as np, soundfile as sf
sys.path.insert(0, os.path.dirname(__file__))
from find_stutter import analyse, peaks, SR

BANDS = [(0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01)]
OUT = sys.argv[2] if len(sys.argv) > 2 else "out/calib"

files = sorted(glob.glob(os.path.join(sys.argv[1], "*.wav")),
               key=lambda f: -os.path.getsize(f))[:10]
os.makedirs(OUT, exist_ok=True)
found = {b: [] for b in BANDS}
rows = []

for f in files:
    y, sr = sf.read(f, dtype="float32")
    if sr != SR or len(y) < SR * 60:
        continue
    x, score, lag = analyse(y)
    hits = peaks(score, lag, 0.60)
    mx = max((h[2] for h in hits), default=0)
    rows.append((os.path.basename(f), len(y)/SR/60, len(hits), mx))
    print(f"  {os.path.basename(f):28s} {len(y)/SR/60:5.1f} мин  "
          f"мест>0.60: {len(hits):4d}  макс {mx:.3f}", file=sys.stderr)
    for t, l, s in hits:
        for b in BANDS:
            if b[0] <= s < b[1] and len(found[b]) < 4:
                a2, b2 = max(0, int((t-3)*SR)), min(len(y), int((t+3)*SR))
                name = f"sim{s:.3f}_{os.path.basename(f)[:12]}_t{int(t)}s.wav"
                sf.write(os.path.join(OUT, name), y[a2:b2], SR)
                found[b].append((name, s, os.path.basename(f), t))

print("\n=== калибровочный набор ===", file=sys.stderr)
for b in BANDS:
    print(f"  сходство {b[0]:.2f}-{b[1]:.2f}: {len(found[b])} клипов", file=sys.stderr)
json.dump({str(k): v for k, v in found.items()},
          open(os.path.join(OUT, "index.json"), "w"), ensure_ascii=False, indent=1)
