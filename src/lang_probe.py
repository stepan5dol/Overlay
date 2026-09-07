"""Use ASR language posteriors as an objective read on the accent defect.

The user labelled one clip as carrying the wrong accent. Whisper decides
what language it is hearing before transcribing; if the narration drifts
towards another language's phonetics, that decision shifts. This compares a
labelled-bad clip against the reference voice and against normal narration.
"""
import sys, glob, os
import numpy as np, soundfile as sf
import mlx_audio.stt.utils as u
from mlx_audio.stt.models.whisper import audio as wa, decoding

MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
SR = 16000


def probs_for(model, path, start_s=0.0, dur_s=None):
    y, sr = sf.read(path, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    import librosa
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    a = int(start_s * SR)
    b = a + int(dur_s * SR) if dur_s else len(y)
    y = y[a:b]
    mel = wa.log_mel_spectrogram(y, n_mels=model.dims.n_mels,
                                 padding=wa.N_SAMPLES)
    seg = mel[:wa.N_FRAMES]
    _, p = decoding.detect_language(model, seg)
    return p[0] if isinstance(p, list) else p


def show(model, label, path, start=0.0, dur=None):
    p = probs_for(model, path, start, dur)
    top = sorted(p.items(), key=lambda kv: -kv[1])[:5]
    ru = p.get("ru", 0.0)
    line = "  ".join(f"{k}={v:.3f}" for k, v in top)
    print(f"  {label:34s} ru={ru:6.3f}   {line}")
    return ru


def main():
    model = u.load_model(MODEL)
    REF = ("/Users/stepandolzhenko/Downloads/ebook2audiobook/voices/__sessions/"
           "voice-2c940a01-ffda-4a74-ab49-f5b8f1be3739/rus/ref_active.wav")
    BAD = "/Users/stepandolzhenko/Documents/Thorium 2.0/out/accent/088_start_30s.wav"
    T = "/Users/stepandolzhenko/qwen3-tts-apple-silicon/temp_chapters"

    print("эталонный голос (заведомо хороший):")
    show(model, "ref_active.wav", REF)

    print("\nпомеченный тобой файл, начало:")
    for d in (2.0, 4.0, 8.0):
        show(model, f"088_ch2_43  первые {d:.0f} с", BAD, 0.0, d)

    print("\nобычные главы, начало против середины:")
    for f in sorted(glob.glob(os.path.join(T, "0[12]*_ch1_1*.wav")))[:4]:
        n = os.path.basename(f)[:18]
        if sf.info(f).duration < 200:
            continue
        show(model, n + " начало 4 с", f, 0.0, 4.0)
        show(model, n + " середина 4 с", f, 120.0, 4.0)


if __name__ == "__main__":
    main()
