"""Score generated samples on two independent measures.

voice_drift  - distance from the reference speaker in the opening window,
               relative to the same generation's steady state. Catches the
               wrong-accent onset.
cer          - character error rate between the text asked for and the text
               actually spoken, via ASR. Catches wordless babble, dropped
               sentences and looping, which no acoustic measure separates
               from ordinary speech reliably.
"""
import os, sys, json, glob, re
import numpy as np, soundfile as sf
import librosa

SR = 24000
W = 0.5


def frames(y, win_s=W):
    n = int(SR * win_s)
    out = []
    for i in range(0, len(y) - n + 1, n):
        s = y[i:i + n]
        if np.sqrt((s ** 2).mean()) < 1e-3:
            out.append(None); continue
        m = librosa.feature.melspectrogram(y=s, sr=SR, n_fft=1024, hop_length=256,
                                           n_mels=40, fmin=50, fmax=8000)
        v = librosa.power_to_db(m.mean(axis=1) + 1e-12)
        out.append(v - v.mean())
    return out


def load(p):
    y, sr = sf.read(p, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    return y


def voice_drift(y, ref_vec, onset_s=1.0):
    f = [v for v in frames(y) if v is not None]
    if len(f) < 4:
        return None
    k = max(1, int(onset_s / W))
    d = [np.linalg.norm(v - ref_vec) for v in f]
    onset, rest = np.mean(d[:k]), np.median(d[k:])
    return float(onset / rest) if rest else None


def norm_text(s):
    s = s.lower().replace("ё", "е")
    return re.sub(r"[^а-яa-z0-9 ]+", " ", s).strip()


def cer(ref, hyp):
    a, b = norm_text(ref), norm_text(hyp)
    if not a:
        return None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / len(a)


def main():
    ref_wav, runs = sys.argv[1], sys.argv[2]
    ref_vec = np.mean([v for v in frames(load(ref_wav)) if v is not None], axis=0)

    import mlx_whisper
    MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"

    rows = []
    for line in open(runs):
        r = json.loads(line)
        for w in r["wavs"]:
            if not os.path.exists(w):
                continue
            y = load(w)
            text = TEXTS.get(r["kind"], "")
            hyp = mlx_whisper.transcribe(w, path_or_hf_repo=MODEL,
                                         language="ru")["text"]
            rows.append({**{k: r[k] for k in ("tag", "call_no", "kind", "cold", "gen_s")},
                         "dur": round(len(y) / SR, 2),
                         "drift": voice_drift(y, ref_vec),
                         "cer": cer(text, hyp),
                         "hyp": hyp.strip()[:120]})
    json.dump(rows, open(os.path.join(os.path.dirname(runs), "scores.json"), "w"),
              ensure_ascii=False, indent=1)

    def agg(sel, label):
        s = [r for r in rows if sel(r)]
        if not s:
            return
        d = [r["drift"] for r in s if r["drift"]]
        c = [r["cer"] for r in s if r["cer"] is not None]
        print(f"  {label:26s} n={len(s):3d}  дрейф {np.median(d):5.3f}  "
              f"CER {np.median(c):6.3f}  худший CER {max(c):6.3f}")

    print("\n=== H1: прогрев ===")
    agg(lambda r: r["cold"] and r["kind"] == "short", "первый вызов (холодный)")
    agg(lambda r: not r["cold"] and r["kind"] == "short", "последующие (прогретые)")
    print("\n=== H2: длина контекста ===")
    agg(lambda r: r["kind"] == "short" and not r["cold"], "короткий (~110 симв.)")
    agg(lambda r: r["kind"] == "long", "длинный (~800 симв.)")


from experiment import SHORT, LONG          # noqa: E402
TEXTS = {"short": SHORT, "long": LONG}

if __name__ == "__main__":
    main()
