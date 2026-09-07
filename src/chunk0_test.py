"""The first chunk of every chapter, as the book generator built it,
against the same text with the injected bare periods removed."""
import os, json, re, glob, shutil
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import warnings; warnings.filterwarnings("ignore")
import numpy as np, soundfile as sf

REF = ("/Users/stepandolzhenko/Downloads/ebook2audiobook/voices/__sessions/"
       "voice-2c940a01-ffda-4a74-ab49-f5b8f1be3739/rus/ref_active.wav")
REF_TEXT = ("Эпистемический релятивизм предполагает, что там что-то есть, но до "
            "тех пор, пока мы не начали это описывать, оно еще не является "
            "обществом, взаимодействием, экономическим, политическим или "
            "каким-либо иным феноменом.")
MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
OUT = "/Users/stepandolzhenko/Documents/Thorium 2.0/out/chunk0"
SR = 24000


def strip_injected(t):
    t = re.sub(r"(?:\s*\.\s*){2,}", ". ", t)      # runs of bare periods
    return re.sub(r"^\s*\.\s*", "", t).strip()


def main():
    from mlx_audio.tts.utils import load_model
    from mlx_audio.tts.generate import generate_audio
    os.makedirs(OUT, exist_ok=True)
    chunk0 = json.load(open("/private/tmp/claude-501/"
                            "-Users-stepandolzhenko-Documents-Thorium-2-0/"
                            "634433fc-1223-4e61-8df8-2bcd42b7a8d6/"
                            "scratchpad/chunk0.json"))
    model = load_model(MODEL)

    jobs = []
    for idx in ("2", "3"):
        raw = chunk0[idx]
        jobs.append((f"ch{idx}_КАК_В_КНИГЕ", raw))
        jobs.append((f"ch{idx}_БЕЗ_ТОЧЕК", strip_injected(raw)))

    for name, text in jobs:
        d = os.path.join(OUT, "_t"); shutil.rmtree(d, ignore_errors=True)
        generate_audio(model=model, text=text, ref_audio=REF, ref_text=REF_TEXT,
                       language="Russian", lang_code="ru", output_path=d,
                       audio_format="wav", file_prefix="c", verbose=False,
                       temperature=0.8, top_p=0.8, repetition_penalty=1.0)
        ws = sorted(glob.glob(os.path.join(d, "**", "*.wav"), recursive=True))
        y = np.concatenate([sf.read(w, dtype="float32")[0] for w in ws])
        sf.write(os.path.join(OUT, name + ".wav"), y, SR)
        print(f"  {name:22s} {len(y)/SR:5.1f}с   текст: {text[:60]!r}", flush=True)
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    main()
