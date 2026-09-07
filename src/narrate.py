"""EPUB -> M4B audiobook.

Text is taken block by block. Inline markup is joined without inserting any
separator, because injecting one puts stray punctuation into the stream --
in particular a run of bare periods at the head of every chapter, which is
what made chapter openings drift off-voice in the previous generator.

Chunks are whole sentences grouped to a target length: short enough to
parallelise across workers, long enough to carry prosody. A chunk that would
be nothing but punctuation is dropped rather than sent to the model.
"""
import argparse, gc, json, os, re, subprocess, sys, unicodedata
import multiprocessing as mp

BLOCKS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "dd", "dt"]
SR = 24000
PUNCT_ONLY = re.compile(r"^[\W\d_]+$", re.UNICODE)


def clean_block(el):
    # no separator: inline tags must not introduce characters of their own
    t = unicodedata.normalize("NFC", el.get_text())
    t = t.replace("­", "").replace("​", "").replace("‌", "")
    t = t.replace("«", "“").replace("»", "”")
    return re.sub(r"\s+", " ", t).strip()


def chapter_text(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for junk in soup(["script", "style", "meta", "link", "sup", "sub"]):
        junk.extract()
    out = []
    for el in soup.find_all(BLOCKS):
        if el.find(BLOCKS):
            continue                       # keep the innermost block only
        t = clean_block(el)
        if not t or PUNCT_ONLY.match(t):
            continue
        if el.name.startswith("h") and t[-1] not in ".!?:":
            t += "."
        out.append(t)
    return out


def split_sentences(p):
    parts = re.split(r"(?<=[.!?”])\s+(?=[“\"(]?[А-ЯA-ZЁ0-9])", p)
    return [s.strip() for s in parts if s.strip()]


def chunks_for(paragraphs, target):
    out, buf = [], ""
    for p in paragraphs:
        for s in split_sentences(p):
            if buf and len(buf) + 1 + len(s) > target:
                out.append(buf); buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            out.append(buf); buf = ""
    return [c for c in out if c and not PUNCT_ONLY.match(c)]


def extract(epub_path, target):
    import ebooklib
    from ebooklib import epub
    book = epub.read_epub(epub_path)
    chapters = []
    for iid, _ in book.spine:
        item = book.get_item_with_id(iid)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        paras = chapter_text(item.get_content())
        text = " ".join(paras)
        if len(text) < 50:
            continue
        title = paras[0][:80].rstrip(".") if paras else item.get_name()
        chapters.append({"title": title, "name": item.get_name(),
                         "chunks": chunks_for(paras, target)})
    return chapters


# ── worker ───────────────────────────────────────────────────────────────
W = {}


def init(model_id, ref_audio, ref_text):
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import warnings; warnings.filterwarnings("ignore")
    from mlx_audio.tts.utils import load_model
    from mlx_audio.tts.generate import generate_audio
    W["model"] = load_model(model_id)
    # ICL cloning is gated on the speech tokenizer exposing an encoder. A
    # loader bug in mlx-audio leaves it unparsed, in which case cloning
    # silently degrades to speaker-embedding-only. Fail loudly instead.
    if not getattr(W["model"].speech_tokenizer, "has_encoder", False):
        raise RuntimeError(
            "ICL недоступен: у токенизатора речи нет энкодера. "
            "Примените patches/enable_icl_encoder.py к venv.")
    W["gen"] = generate_audio
    W["ref_audio"], W["ref_text"] = ref_audio, ref_text
    import tempfile
    with tempfile.TemporaryDirectory() as d:          # warm the MLX graph
        generate_audio(model=W["model"], text="Готово.", ref_audio=ref_audio,
                       ref_text=ref_text, language="Russian", lang_code="ru",
                       output_path=d, audio_format="wav", file_prefix="w",
                       verbose=False)


def synth(task):
    import glob, shutil
    text, path, temperature, top_p = task
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    d = path + ".d"
    shutil.rmtree(d, ignore_errors=True)
    try:
        W["gen"](model=W["model"], text=text, ref_audio=W["ref_audio"],
                 ref_text=W["ref_text"], language="Russian", lang_code="ru",
                 output_path=d, audio_format="wav", file_prefix="c",
                 verbose=False, temperature=temperature, top_p=top_p)
        import numpy as np, soundfile as sf
        ws = sorted(glob.glob(os.path.join(d, "**", "*.wav"), recursive=True))
        if not ws:
            return None
        y = np.concatenate([sf.read(w, dtype="float32")[0] for w in ws])
        sf.write(path, y, SR)
        return path
    except Exception as e:
        print(f"    сбой: {e}", file=sys.stderr, flush=True)
        return None
    finally:
        shutil.rmtree(d, ignore_errors=True)
        gc.collect()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epub", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref-audio", required=True)
    ap.add_argument("--ref-text", required=True, help="файл с расшифровкой референса")
    ap.add_argument("--model", default="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit")
    ap.add_argument("--target", type=int, default=200)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-p", type=float, default=0.8)
    ap.add_argument("--only", type=int, default=None, help="озвучить одну главу")
    args = ap.parse_args()

    ref_text = open(args.ref_text, encoding="utf-8").read().strip()
    parts = os.path.join(args.out, "parts"); os.makedirs(parts, exist_ok=True)
    chapters = extract(args.epub, args.target)
    if args.only is not None:
        chapters = chapters[args.only:args.only + 1]
    json.dump(chapters, open(os.path.join(args.out, "chapters.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"глав: {len(chapters)}, чанков: {sum(len(c['chunks']) for c in chapters)}")

    tasks = []
    for ci, ch in enumerate(chapters):
        for i, t in enumerate(ch["chunks"]):
            tasks.append((t, os.path.join(parts, f"{ci:04d}_{i:04d}.wav"),
                          args.temperature, args.top_p))
    todo = [t for t in tasks if not os.path.exists(t[1])]
    print(f"к синтезу: {len(todo)} (готово: {len(tasks)-len(todo)})")

    if todo:
        with mp.Pool(args.workers, initializer=init,
                     initargs=(args.model, args.ref_audio, ref_text)) as pool:
            done = 0
            for _ in pool.imap_unordered(synth, todo):
                done += 1
                if done % 10 == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)}", flush=True)
    print("готово")


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
