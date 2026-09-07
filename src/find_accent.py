"""Find chapters whose opening does not sound like the rest of the book.

Builds a fingerprint of each chapter's first seconds -- long-term average
spectrum plus pitch statistics -- and ranks chapters by distance from the
book-wide norm. No threshold is assumed; the ranking is the output, and the
top of it gets cut into clips for confirmation by ear.
"""
import os, sys, glob, json
import numpy as np, soundfile as sf
import librosa

SR = 24000


def fingerprint(y):
    if len(y) < SR:
        return None
    S = np.abs(librosa.stft(y, n_fft=1024, hop_length=256))
    mel = librosa.feature.melspectrogram(S=S**2, sr=SR, n_mels=40, fmin=50, fmax=8000)
    ltas = librosa.power_to_db(mel.mean(axis=1) + 1e-12)
    ltas = ltas - ltas.mean()
    f0 = librosa.yin(y, fmin=60, fmax=400, sr=SR, frame_length=1024)
    f0 = f0[np.isfinite(f0)]
    if len(f0) < 10:
        return None
    stats = np.array([np.median(f0), np.percentile(f0, 90) - np.percentile(f0, 10)])
    return ltas, stats


def main():
    d = sys.argv[1]
    head_s = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    files = sorted(glob.glob(os.path.join(d, "*.wav")))
    names, ltas, stats = [], [], []
    for f in files:
        try:
            y, sr = sf.read(f, dtype="float32", frames=int(SR * head_s))
        except Exception:
            continue
        if sr != SR:
            continue
        fp = fingerprint(y)
        if fp is None:
            continue
        names.append(os.path.basename(f))
        ltas.append(fp[0]); stats.append(fp[1])

    L = np.array(ltas); P = np.array(stats)
    med = np.median(L, axis=0)
    mad = np.median(np.abs(L - med), axis=0) + 1e-6
    d_spec = np.abs((L - med) / mad).mean(axis=1)
    pm, pmad = np.median(P, axis=0), np.median(np.abs(P - np.median(P, axis=0)), axis=0) + 1e-6
    d_pitch = np.abs((P - pm) / pmad).mean(axis=1)
    score = d_spec + d_pitch

    order = np.argsort(-score)
    print(f"глав: {len(names)}, окно {head_s:.0f} с от начала")
    print(f"медиана отклонения {np.median(score):.2f}, "
          f"90-й перцентиль {np.percentile(score,90):.2f}\n")
    print("самые непохожие на остальную книгу:")
    for i in order[:15]:
        mark = "   <-- твой файл" if names[i].startswith("088_") else ""
        print(f"  {score[i]:6.2f}  спектр {d_spec[i]:5.2f}  тон {d_pitch[i]:5.2f}  "
              f"F0 {P[i][0]:5.1f} Гц  {names[i]}{mark}")

    j = [k for k, n in enumerate(names) if n.startswith("088_")]
    if j:
        k = j[0]
        rank = int(np.flatnonzero(order == k)[0]) + 1
        print(f"\n088_ch2_43: место {rank} из {len(names)} по непохожести, "
              f"отклонение {score[k]:.2f} при медиане {np.median(score):.2f}")
        print(f"  F0 медиана {P[k][0]:.1f} Гц против {pm[0]:.1f} Гц по книге")

    json.dump({n: float(s) for n, s in zip(names, score)},
              open(os.path.join(os.path.dirname(d), "accent_scores.json"), "w"))
    return names, score, order


if __name__ == "__main__":
    main()
