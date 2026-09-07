"""Locate stutter/repetition artifacts in generated narration.

A stuck autoregressive generation re-emits the same codec tokens, so the
waveform repeats almost sample-exactly. Natural speech is periodic too, but
never that exact at 80-600 ms lags -- so normalised cross-correlation of the
raw waveform separates the two, where spectral similarity does not.

No threshold is assumed: the score distribution is reported so the operating
point can be read off the data.
"""
import argparse, json, os
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from scipy.ndimage import uniform_filter1d

SR = 24000
WORK_SR = 8000


def ncc_by_lag(x, win, lags):
    """Windowed normalised cross-correlation of x against itself at each lag."""
    best = np.zeros(len(x), dtype=np.float32)
    best_lag = np.zeros(len(x), dtype=np.int32)
    e = uniform_filter1d(x * x, win, mode="constant")
    for L in lags:
        a, b = x[:-L], x[L:]
        num = uniform_filter1d(a * b, win, mode="constant")
        den = np.sqrt(np.maximum(e[:-L] * e[L:], 0)) + 1e-9
        s = num / den
        upd = s > best[:-L]
        best[:-L][upd] = s[upd]
        best_lag[:-L][upd] = L
    return best, best_lag


def analyse(y, min_lag_ms=80, max_lag_ms=600, win_ms=200, quiet_db=-45):
    x = resample_poly(y, WORK_SR, SR).astype(np.float32)
    win = int(win_ms * WORK_SR / 1000)
    lags = [int(m * WORK_SR / 1000) for m in range(min_lag_ms, max_lag_ms + 1, 10)]
    score, lag = ncc_by_lag(x, win, lags)
    rms = np.sqrt(uniform_filter1d(x * x, win, mode="constant") + 1e-12)
    loud = 20 * np.log10(rms + 1e-12) > quiet_db
    score[~loud] = 0
    return x, score, lag


def peaks(score, lag, thresh, min_gap_s=1.0):
    idx = np.flatnonzero(score > thresh)
    out = []
    for i in idx:
        t = i / WORK_SR
        if out and t - out[-1][0] < min_gap_s:
            if score[i] > out[-1][2]:
                out[-1] = (out[-1][0], lag[i] / WORK_SR * 1000, float(score[i]))
        else:
            out.append((t, lag[i] / WORK_SR * 1000, float(score[i])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--clips")
    ap.add_argument("--thresh", type=float, default=None)
    ap.add_argument("--max-clips", type=int, default=10)
    ap.add_argument("--lead", type=float, default=3.0)
    args = ap.parse_args()

    y, sr = sf.read(args.wav, dtype="float32")
    assert sr == SR
    x, score, lag = analyse(y)
    dur = len(y) / SR

    voiced = score[score > 0]
    qs = [50, 90, 99, 99.9, 99.99]
    print(f"{os.path.basename(args.wav)}: {dur/60:.1f} мин")
    print("распределение сходства волны (только громкие участки):")
    for q in qs:
        print(f"  {q:6.2f}%  {np.percentile(voiced, q):.4f}")
    print(f"  макс     {voiced.max():.4f}")

    th = args.thresh if args.thresh is not None else 0.90
    hits = peaks(score, lag, th)
    print(f"\nпорог {th}: {len(hits)} мест  ({len(hits)/(dur/60):.2f} на минуту)")
    for t, l, s in hits[:15]:
        print(f"  {int(t)//60:3d}:{t%60:05.2f}  период {l:5.1f} мс  сходство {s:.4f}")

    if args.clips and hits:
        os.makedirs(args.clips, exist_ok=True)
        hits_sorted = sorted(hits, key=lambda h: -h[2])[: args.max_clips]
        for k, (t, l, s) in enumerate(hits_sorted):
            a, b = max(0, int((t - args.lead) * SR)), min(len(y), int((t + 3) * SR))
            sf.write(os.path.join(args.clips,
                     f"{k:02d}_t{int(t)}s_sim{s:.3f}.wav"), y[a:b], SR)
        with open(os.path.join(args.clips, "hits.json"), "w") as f:
            json.dump([{"t": t, "lag_ms": l, "sim": s} for t, l, s in hits], f)
        print(f"\n{len(hits_sorted)} клипов (самые сильные) → {args.clips}/")


if __name__ == "__main__":
    main()
