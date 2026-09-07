"""Prevalence of the wrong-accent onset across the whole book.

Metric: ASR posterior for Russian on the opening seconds of a chapter,
against the same chapter's steady state. Validated against a clip the
listener labelled as defective (ru=0.052 on its first 2 s, versus 0.999
for the reference voice).
"""
import sys, glob, os, json
import numpy as np, soundfile as sf, librosa
import mlx_audio.stt.utils as u
from mlx_audio.stt.models.whisper import audio as wa, decoding

MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
SR = 16000


def ru_prob(model, y):
    mel = wa.log_mel_spectrogram(y, n_mels=model.dims.n_mels, padding=wa.N_SAMPLES)
    _, p = decoding.detect_language(model, mel[:wa.N_FRAMES])
    p = p[0] if isinstance(p, list) else p
    return float(p.get("ru", 0.0)), max(p.items(), key=lambda kv: kv[1])


def take(path, start_s, dur_s):
    info = sf.info(path)
    a = int(start_s * info.samplerate)
    n = int(dur_s * info.samplerate)
    if a + n > info.frames:
        return None
    y, sr = sf.read(path, dtype="float32", start=a, frames=n)
    if y.ndim > 1:
        y = y.mean(axis=1)
    return librosa.resample(y, orig_sr=sr, target_sr=SR) if sr != SR else y


def main():
    model = u.load_model(MODEL)
    files = sorted(glob.glob(os.path.join(sys.argv[1], "*.wav")))
    rows = []
    for f in files:
        head = take(f, 0.0, 4.0)
        if head is None:
            continue
        ru_h, top_h = ru_prob(model, head)
        mid = take(f, 60.0, 4.0)
        ru_m = ru_prob(model, mid)[0] if mid is not None else None
        rows.append({"file": os.path.basename(f), "ru_head": ru_h,
                     "ru_mid": ru_m, "top_head": top_h[0],
                     "top_p": round(float(top_h[1]), 3)})
        print(f"  {rows[-1]['file'][:26]:26s} начало ru={ru_h:.3f} "
              f"({top_h[0]}={top_h[1]:.2f})"
              + (f"  середина ru={ru_m:.3f}" if ru_m is not None else ""),
              flush=True)

    json.dump(rows, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
    h = np.array([r["ru_head"] for r in rows])
    m = np.array([r["ru_mid"] for r in rows if r["ru_mid"] is not None])
    print(f"\nглав: {len(rows)}")
    print(f"начало  ru: медиана {np.median(h):.3f}, "
          f"<0.9 у {(h<0.9).sum()} ({(h<0.9).mean()*100:.0f}%), "
          f"<0.5 у {(h<0.5).sum()} ({(h<0.5).mean()*100:.0f}%)")
    if len(m):
        print(f"середина ru: медиана {np.median(m):.3f}, "
              f"<0.9 у {(m<0.9).sum()} ({(m<0.9).mean()*100:.0f}%)")


if __name__ == "__main__":
    main()
