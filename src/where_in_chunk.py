"""Test whether repetition artifacts cluster at the end of a generation.

shorttest.py wrote PAUSE_SENTENCE=0.6 s / PAUSE_COMMA=0.15 s of digital zero
between chunks, so generation boundaries are recoverable exactly. Each
detected repetition is mapped to its relative position inside its own
generation; a flat histogram means position does not matter, a rising one
confirms tail degradation.
"""
import os, sys, glob
import numpy as np, soundfile as sf
sys.path.insert(0, os.path.dirname(__file__))
from find_stutter import analyse, peaks, SR

MIN_PAUSE = 0.10


def generations(y):
    z = np.concatenate(([0], (y == 0).view(np.int8), [0]))
    d = np.diff(z)
    s, e = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    keep = (e - s) >= int(SR * MIN_PAUSE)
    segs, prev = [], 0
    for a, b in zip(s[keep], e[keep]):
        if a > prev:
            segs.append((prev, a))
        prev = b
    if len(y) > prev:
        segs.append((prev, len(y)))
    return [(a, b) for a, b in segs if b - a > SR * 1.0]


def main():
    files = sorted(glob.glob(os.path.join(sys.argv[1], "*.wav")),
                   key=lambda f: -os.path.getsize(f))[:10]
    thresh = float(sys.argv[2]) if len(sys.argv) > 2 else 0.75
    rel_all, durs, nseg = [], [], 0
    for f in files:
        y, sr = sf.read(f, dtype="float32")
        if sr != SR or len(y) < SR * 60:
            continue
        segs = generations(y)
        nseg += len(segs)
        durs += [(b - a) / SR for a, b in segs]
        _, score, lag = analyse(y)
        for t, l, s in peaks(score, lag, thresh):
            i = int(t * SR)
            for a, b in segs:
                if a <= i < b:
                    rel_all.append((i - a) / (b - a))
                    break

    durs = np.array(durs)
    rel = np.array(rel_all)
    print(f"генераций: {nseg}, медиана {np.median(durs):.1f} с, "
          f"90-й перцентиль {np.percentile(durs, 90):.1f} с")
    print(f"повторов (порог {thresh}): {len(rel)}\n")
    print("положение повтора внутри своей генерации:")
    h, edges = np.histogram(rel, bins=10, range=(0, 1))
    exp = len(rel) / 10
    for k in range(10):
        bar = "#" * int(h[k] / max(h.max(), 1) * 44)
        flag = "  <<<" if h[k] > exp * 1.5 else ""
        print(f"  {edges[k]:.1f}-{edges[k+1]:.1f}  {h[k]:5d}  {bar}{flag}")
    print(f"\nравномерно было бы по {exp:.0f} на корзину")
    last, first = (rel > 0.8).sum(), (rel < 0.2).sum()
    print(f"последние 20% генерации: {last}   первые 20%: {first}   "
          f"отношение {last/max(first,1):.2f}")


if __name__ == "__main__":
    main()
