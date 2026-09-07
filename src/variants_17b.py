"""Same passage, one setting changed at a time. For listening, not scoring.

Baseline reproduces exactly what shorttest.py used for the existing book.
Each other variant differs from it in a single respect, so a difference you
hear can be attributed.
"""
import os, re, sys, time, glob, shutil
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import warnings; warnings.filterwarnings("ignore")
import numpy as np, soundfile as sf

REF = ("/Users/stepandolzhenko/Downloads/ebook2audiobook/voices/__sessions/"
       "voice-2c940a01-ffda-4a74-ab49-f5b8f1be3739/rus/ref_active.wav")
REF_TEXT = ("Эпистемический релятивизм предполагает, что там что-то есть, но до "
            "тех пор, пока мы не начали это описывать, оно еще не является "
            "обществом, взаимодействием, экономическим, политическим или "
            "каким-либо иным феноменом.")
MODEL = "/Users/stepandolzhenko/qwen3-tts-apple-silicon/qwen3-tts-patched"
OUT = "/Users/stepandolzhenko/Documents/Thorium 2.0/out/variants_17b"
SR = 24000

TEXT = open(sys.argv[1]).read().strip() if len(sys.argv) > 1 else None

# baseline == shorttest.py, the settings that produced the existing audiobook
BASE = dict(chunk=800, temperature=0.8, top_p=0.8, repetition_penalty=1.0,
            warmup=False)

VARIANTS = [
    ("A_как_в_книге",        {}),
    ("B_плюс_прогрев",       dict(warmup=True)),
    ("C_чанк_200",           dict(chunk=200)),
    ("D_rep_penalty_1.1",    dict(repetition_penalty=1.1)),
    ("E_temp_0.6",           dict(temperature=0.6)),
    ("F_всё_вместе",         dict(warmup=True, chunk=200,
                                  repetition_penalty=1.1, temperature=0.6)),
]


def split(text, limit):
    sents = re.split(r"(?<=[.!?])\s+", text)
    out, buf = [], ""
    for s in sents:
        if buf and len(buf) + 1 + len(s) > limit:
            out.append(buf); buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        out.append(buf)
    return out


def main():
    from mlx_audio.tts.utils import load_model
    from mlx_audio.tts.generate import generate_audio
    os.makedirs(OUT, exist_ok=True)
    model = load_model(MODEL)

    for name, over in VARIANTS:
        cfg = {**BASE, **over}
        tmp = os.path.join(OUT, "_tmp"); shutil.rmtree(tmp, ignore_errors=True)
        t0 = time.time()

        if cfg["warmup"]:
            generate_audio(model=model, text="Прогрев.", ref_audio=REF,
                           ref_text=REF_TEXT, language="Russian", lang_code="ru",
                           output_path=os.path.join(tmp, "w"), audio_format="wav",
                           file_prefix="w", verbose=False)

        pieces = []
        for i, chunk in enumerate(split(TEXT, cfg["chunk"])):
            d = os.path.join(tmp, f"c{i:02d}")
            generate_audio(
                model=model, text=chunk, ref_audio=REF, ref_text=REF_TEXT,
                language="Russian", lang_code="ru", output_path=d,
                audio_format="wav", file_prefix="c", verbose=False,
                temperature=cfg["temperature"], top_p=cfg["top_p"],
                repetition_penalty=cfg["repetition_penalty"],
            )
            for w in sorted(glob.glob(os.path.join(d, "**", "*.wav"), recursive=True)):
                y, _ = sf.read(w, dtype="float32")
                pieces.append(y if y.ndim == 1 else y.mean(axis=1))

        if pieces:
            audio = np.concatenate(pieces)
            path = os.path.join(OUT, f"{name}.wav")
            sf.write(path, audio, SR)
            print(f"  {name:22s} {len(audio)/SR:6.1f}с  "
                  f"чанков={len(pieces)}  синтез {time.time()-t0:5.1f}с", flush=True)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
