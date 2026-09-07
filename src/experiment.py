"""Test the two hypotheses about the onset defect, by generating.

H1 (warmup): the first generate call in a fresh process comes out worse than
    later calls in the same process.
H2 (context length): a long chunk degrades where a short one does not.

Both are stochastic, so each condition is repeated and compared on a metric,
not by ear. Cold samples require a fresh process, so this script produces one
cold sample per invocation and is meant to be run several times; results
accumulate as JSON lines.
"""
import os, sys, json, time, glob, shutil
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import warnings; warnings.filterwarnings("ignore")

REF = ("/Users/stepandolzhenko/Downloads/ebook2audiobook/voices/__sessions/"
       "voice-2c940a01-ffda-4a74-ab49-f5b8f1be3739/rus/ref_active.wav")
MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit"
ROOT = "/Users/stepandolzhenko/Documents/Thorium 2.0/out/exp"
LOG = os.path.join(ROOT, "runs.jsonl")

SHORT = ("Социальное не является особым видом связи между людьми. "
         "Оно есть лишь след, оставленный перемещением.")
LONG = SHORT + " " + (
    "Акторно-сетевая теория предлагает считать социальное не готовым "
    "материалом, из которого якобы сделаны сообщества, а результатом "
    "непрерывной работы по сборке. Всякий раз, когда исследователь "
    "объявляет некоторое явление социальным, он на деле указывает на "
    "цепочку посредников, каждый из которых что-то переводит и "
    "искажает. Именно поэтому объяснение через общество ничего не "
    "объясняет: оно подменяет описание связей ссылкой на сущность, "
    "которую никто никогда не наблюдал непосредственно. "
    "Задача состоит в том, чтобы вернуться к самим ассоциациям и "
    "проследить их, не опираясь на заранее принятые категории.")


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else str(int(time.time()))
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    ref_text_path = os.path.join(ROOT, "ref_text.txt")
    ref_text = open(ref_text_path).read().strip() if os.path.exists(ref_text_path) else None

    from mlx_audio.tts.utils import load_model
    from mlx_audio.tts.generate import generate_audio
    t0 = time.time()
    model = load_model(MODEL)
    load_s = time.time() - t0

    out = open(LOG, "a")
    plan = [("short", SHORT)] * reps + [("long", LONG)] * 3
    for call_no, (kind, text) in enumerate(plan, start=1):
        d = os.path.join(ROOT, f"{tag}_call{call_no:02d}_{kind}")
        shutil.rmtree(d, ignore_errors=True)
        t0 = time.time()
        ok = True
        try:
            generate_audio(
                model=model, text=text, ref_audio=REF, ref_text=ref_text,
                language="Russian", lang_code="ru", output_path=d,
                audio_format="wav", file_prefix="a", verbose=False,
                temperature=0.8, top_p=0.8, repetition_penalty=1.0,
            )
        except Exception as e:
            ok = False
            print(f"  call{call_no} FAILED: {e}", flush=True)
        wavs = sorted(glob.glob(os.path.join(d, "**", "*.wav"), recursive=True))
        rec = {"tag": tag, "call_no": call_no, "kind": kind, "ok": ok,
               "cold": call_no == 1, "gen_s": round(time.time() - t0, 2),
               "load_s": round(load_s, 2), "chars": len(text),
               "wavs": wavs}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        print(f"  call{call_no:02d} {kind:5s} cold={rec['cold']} "
              f"{rec['gen_s']:6.1f}s -> {len(wavs)} wav", flush=True)
    out.close()


if __name__ == "__main__":
    main()
