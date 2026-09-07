"""Does every chapter start off-voice and converge?

Measures distance from the reference speaker over time since the start of
each chapter, averaged across all chapters. A flat curve means the opening
sounds like the rest; a curve that starts high and decays is the reported
defect, and its decay time says how long the bad opening lasts.
"""
import os, sys, glob
import numpy as np, soundfile as sf
import librosa

SR = 24000
WIN = 0.5          # seconds per measurement point
HEAD = 30.0        # how far into the chapter to look


def logmel_frames(y, win_s):
    n = int(SR * win_s)
    out = []
    for i in range(0, len(y) - n + 1, n):
        seg = y[i:i + n]
        if np.sqrt((seg ** 2).mean()) < 1e-3:      # skip silence
            out.append(None)
            continue
        m = librosa.feature.melspectrogram(y=seg, sr=SR, n_fft=1024,
                                           hop_length=256, n_mels=40,
                                           fmin=50, fmax=8000)
        v = librosa.power_to_db(m.mean(axis=1) + 1e-12)
        out.append(v - v.mean())
    return out


def main():
    ref_path, chap_dir = sys.argv[1], sys.argv[2]
    ry, rsr = sf.read(ref_path, dtype="float32")
    if ry.ndim > 1:
        ry = ry.mean(axis=1)
    if rsr != SR:
        ry = librosa.resample(ry, orig_sr=rsr, target_sr=SR)
    ref = np.mean([v for v in logmel_frames(ry, WIN) if v is not None], axis=0)

    nbins = int(HEAD / WIN)
    acc = [[] for _ in range(nbins)]
    tail = []
    files = sorted(glob.glob(os.path.join(chap_dir, "*.wav")))
    used = 0
    for f in files:
        try:
            y, sr = sf.read(f, dtype="float32", frames=int(SR * HEAD))
        except Exception:
            continue
        if sr != SR or len(y) < SR * 5:
            continue
        used += 1
        for k, v in enumerate(logmel_frames(y, WIN)[:nbins]):
            if v is not None:
                acc[k].append(np.linalg.norm(v - ref))
        info = sf.info(f)
        if info.duration > 180:                     # steady-state sample
            y2, _ = sf.read(f, dtype="float32",
                            start=int(SR * 120), frames=int(SR * 10))
            tail += [np.linalg.norm(v - ref)
                     for v in logmel_frames(y2, WIN) if v is not None]

    base = np.median(tail) if tail else np.nan
    print(f"глав измерено: {used}, эталон: {os.path.basename(ref_path)}")
    print(f"установившееся расстояние (120-130 с внутрь главы): {base:.2f}\n")
    print("расстояние до эталонного голоса от начала главы:")
    for k in range(nbins):
        if not acc[k]:
            continue
        m = np.median(acc[k])
        rel = m / base if base == base else 1
        bar = "#" * int(max(0, (m - base)) / max(base, 1e-6) * 60)
        print(f"  {k*WIN:5.1f}-{(k+1)*WIN:4.1f} с  {m:6.2f}  "
              f"({rel:4.2f}x от нормы) {bar}")
        if k * WIN >= 12:
            break


if __name__ == "__main__":
    main()
