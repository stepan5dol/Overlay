"""Segment generated chapter WAVs back into individual model generations
and locate anomalies inside them.

The generator wrote fixed-length runs of digital zero between chunks
(0.8 s after sentences, 0.2 s after commas). Those runs are exact, so the
chunk boundaries can be recovered without guessing.
"""
import argparse, json, os, sys
import numpy as np
import soundfile as sf

SR = 24000
FRAME = 480                      # 20 ms


def zero_runs(x, min_len):
    """[(start, end)] of runs of exact zero at least min_len samples long."""
    z = np.concatenate(([0], (x == 0).view(np.int8), [0]))
    d = np.diff(z)
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    keep = (ends - starts) >= min_len
    return list(zip(starts[keep], ends[keep]))


def segments(x, min_pause=0.15):
    """Audio between the injected silences = one model generation each."""
    pauses = zero_runs(x, int(SR * min_pause))
    out, prev = [], 0
    for s, e in pauses:
        if s > prev:
            out.append((prev, s, (e - s) / SR))
        prev = e
    if len(x) > prev:
        out.append((prev, len(x), 0.0))
    return out


def envelope(seg):
    n = len(seg) // FRAME * FRAME
    if n == 0:
        return np.zeros(1)
    return np.sqrt((seg[:n].reshape(-1, FRAME) ** 2).mean(axis=1)) + 1e-9


def tail_repetition(seg, tail_s=2.0, min_lag=0.08, max_lag=0.60):
    """Peak normalised autocorrelation of the loudness envelope in the tail.

    A generation that gets stuck repeating the same acoustic burst shows a
    strong periodic peak here; ordinary speech does not.
    """
    tail = seg[-int(SR * tail_s):] if len(seg) > SR * tail_s else seg
    e = envelope(tail)
    if len(e) < 12:
        return 0.0, 0.0
    e = e - e.mean()
    if not np.any(e):
        return 0.0, 0.0
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac /= ac[0]
    lo, hi = int(min_lag * SR / FRAME), min(int(max_lag * SR / FRAME), len(ac) - 1)
    if hi <= lo:
        return 0.0, 0.0
    k = lo + int(np.argmax(ac[lo:hi]))
    return float(ac[k]), k * FRAME / SR


def analyse(path, limit=None):
    x, sr = sf.read(path, dtype="float32")
    assert sr == SR, sr
    rows = []
    for i, (s, e, pause) in enumerate(segments(x)):
        seg = x[s:e]
        if len(seg) < FRAME * 4:
            continue
        env = envelope(seg)
        peak, lag = tail_repetition(seg)
        # where in the generation does the loudest sustained energy sit
        rows.append({
            "i": i, "t": round(s / SR, 2), "dur": round(len(seg) / SR, 3),
            "pause": round(pause, 2),
            "tail_rep": round(peak, 3), "tail_lag": round(lag, 3),
            "rms": round(float(env.mean()), 5),
            "tail_rms_ratio": round(float(env[-25:].mean() / env.mean()), 3),
        })
        if limit and len(rows) >= limit:
            break
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wavs", nargs="+")
    ap.add_argument("--out")
    args = ap.parse_args()
    all_rows = {}
    for p in args.wavs:
        rows = analyse(p)
        all_rows[os.path.basename(p)] = rows
        d = np.array([r["dur"] for r in rows]) if rows else np.zeros(1)
        rep = np.array([r["tail_rep"] for r in rows]) if rows else np.zeros(1)
        print(f"{os.path.basename(p):30s} генераций={len(rows):5d} "
              f"медиана={np.median(d):6.2f}с макс={d.max():7.2f}с "
              f"tail_rep>0.5: {(rep > 0.5).sum():4d} ({(rep > 0.5).mean() * 100:.1f}%)",
              file=sys.stderr)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(all_rows, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
