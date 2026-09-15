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


def init(model_id, ref_audio, ref_text, voice=None, language="Russian",
         lang_code="ru"):
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import warnings; warnings.filterwarnings("ignore")
    from mlx_audio.tts.utils import load_model
    from mlx_audio.tts.generate import generate_audio
    W["model"] = load_model(model_id)
    # ICL cloning is gated on the speech tokenizer exposing an encoder. A
    # loader bug in mlx-audio leaves it unparsed, in which case cloning
    # silently degrades to speaker-embedding-only. Fail loudly instead.
    if ref_audio and not getattr(getattr(W["model"], "speech_tokenizer", None),
                                 "has_encoder", False):
        raise RuntimeError(
            "ICL недоступен: у токенизатора речи нет энкодера. "
            "Примените patches/enable_icl_encoder.py к venv.")
    W["gen"] = generate_audio
    W["ref_audio"], W["ref_text"] = ref_audio, ref_text
    W["voice"], W["language"], W["lang_code"] = voice, language, lang_code
    W["engine"] = os.environ.get("OVERLAY_ENGINE", "qwen")
    import tempfile
    with tempfile.TemporaryDirectory() as d:          # warm the MLX graph
        generate_audio(model=W["model"], text="Ready.", ref_audio=ref_audio,
                       ref_text=ref_text, voice=voice or "af_heart",
                       language=language, lang_code=lang_code,
                       output_path=d, audio_format="wav", file_prefix="w",
                       verbose=False)


def synth(task):
    import glob, shutil
    text, path, temperature, top_p = task
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    import numpy as np, soundfile as sf
    d = path + ".d"
    # A dropped chunk is a sentence missing from the book, so a transient
    # failure is retried rather than skipped.
    for attempt in range(3):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)      # the writer will not create it
        try:
            if W["engine"].startswith("kokoro"):
                # Kokoro не клонирует и не знает температуры: голос задаётся
                # именем, язык -- однобуквенным кодом (a/b -- англ., ...).
                W["gen"](model=W["model"], text=text,
                         voice=W["voice"] or "af_heart",
                         lang_code=W["lang_code"], output_path=d,
                         audio_format="wav", file_prefix="c", verbose=False)
            else:
                W["gen"](model=W["model"], text=text, ref_audio=W["ref_audio"],
                         ref_text=W["ref_text"], voice=W["voice"] or "af_heart",
                         language=W["language"], lang_code=W["lang_code"],
                         output_path=d, audio_format="wav", file_prefix="c",
                         verbose=False, temperature=temperature, top_p=top_p)
            ws = sorted(glob.glob(os.path.join(d, "**", "*.wav"), recursive=True))
            if not ws:
                continue
            y = np.concatenate([sf.read(w, dtype="float32")[0] for w in ws])
            sf.write(path, y, SR)
            return path
        except Exception as e:
            print(f"    попытка {attempt + 1}/3 не удалась: {e}",
                  file=sys.stderr, flush=True)
        finally:
            shutil.rmtree(d, ignore_errors=True)
            gc.collect()
    print(f"    ЧАНК ПОТЕРЯН: {text[:60]!r}", file=sys.stderr, flush=True)
    return None


def appletts_binary():
    """Помощник синтеза системным голосом: рядом в app/ или внутри бандла."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    # Внутри бандла лежит рядом с src/, при разработке -- в app/
    for c in (os.path.join(root, "appletts"),
              os.path.join(root, "app", "appletts")):
        if os.path.exists(c):
            return c
    return None


def synth_batch(chapters, parts, cmd, label):
    """Синтез пакетами: все задания уходят разом, ответы приходят по мере
    готовности.

    Отличие от synth_stream: там на каждое задание ждут ответ, а батч-
    помощник читает stdin до конца, прежде чем начать -- получалась
    взаимная блокировка.
    """
    tasks = []
    for ci, ch in enumerate(chapters):
        for i, text in enumerate(ch["chunks"]):
            name = f"{ci:04d}_{i:04d}"
            if not os.path.exists(os.path.join(parts, name + ".wav")):
                tasks.append({"id": name, "text": text})
    print(f"к синтезу: {len(tasks)}", flush=True)
    if not tasks:
        return {}

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, bufsize=1)
    for t in tasks:
        proc.stdin.write(json.dumps(t, ensure_ascii=False) + "\n")
    proc.stdin.close()

    from tqdm import tqdm
    bar = tqdm(total=len(tasks), unit="фрагмент", ncols=88)
    сделано = 0
    for line in proc.stdout:
        line = line.strip()
        if not line.startswith("{"):
            continue
        r = json.loads(line)
        if r.get("error"):
            print(f"    не озвучено {r['id']}: {r['error']}", file=sys.stderr)
        else:
            сделано += 1
        bar.update(1)
    bar.close()
    proc.wait()
    if not сделано:
        sys.exit(f"{label}: не озвучено ни одного фрагмента")
    return {}


def synth_stream(chapters, parts, cmd, label):
    # ниже: пустой результат считается сбоем, а не успехом
    """Синтез внешним помощником, который читает задания из stdin.

    Так работают движки, живущие в своём окружении: системный голос Apple и
    русская Kokoro. Один процесс на весь прогон -- модель грузится однажды.
    """
    tasks = []
    for ci, ch in enumerate(chapters):
        for i, text in enumerate(ch["chunks"]):
            name = f"{ci:04d}_{i:04d}"
            if not os.path.exists(os.path.join(parts, name + ".wav")):
                tasks.append({"id": name, "text": text})
    print(f"к синтезу: {len(tasks)}", flush=True)
    if not tasks:
        return {}

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, bufsize=1)
    from tqdm import tqdm
    bar = tqdm(total=len(tasks), unit="фрагмент", ncols=88)
    extra, seen = {}, -1
    for t in tasks:
        proc.stdin.write(json.dumps(t, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            break
        r = json.loads(line)
        if r.get("error") or not r.get("seconds"):
            print(f"    не озвучено: {t['text'][:50]!r}", file=sys.stderr)
        else:
            extra[r["id"]] = r
        ci = int(t["id"].split("_")[0])
        if ci != seen:
            seen = ci
            print(f"ГЛАВА {ci + 1} {chapters[ci]['title'][:60]}", flush=True)
        bar.update(1)
    bar.close()
    proc.stdin.close()
    proc.wait()
    if tasks and not extra:
        sys.exit(f"{label}: не озвучено ни одного фрагмента")
    return extra


def synth_apple(chapters, parts, voice, rate, limit=None):
    """Системный синтез Apple: один процесс на весь список фрагментов.

    В отличие от нейросетевого движка здесь возвращаются границы каждого
    слова, поэтому подсветку можно вести пословно. Они складываются в
    words.json рядом с фрагментами.
    """
    binary = appletts_binary()
    if not binary:
        sys.exit("не найден appletts; соберите его: app/build.sh")

    tasks = []
    for ci, ch in enumerate(chapters):
        for i, text in enumerate(ch["chunks"]):
            name = f"{ci:04d}_{i:04d}"
            if not os.path.exists(os.path.join(parts, name + ".wav")):
                tasks.append({"id": name, "text": text})
    print(f"к синтезу: {len(tasks)}", flush=True)
    if not tasks:
        return

    cmd = [binary, "--out", parts]
    if voice:
        cmd += ["--voice", voice]
    if rate:
        cmd += ["--rate", str(rate)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, bufsize=1)
    from tqdm import tqdm
    bar = tqdm(total=len(tasks), unit="фрагмент", ncols=88)
    words = {}
    for t in tasks:
        proc.stdin.write(json.dumps(t, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            break
        r = json.loads(line)
        if r.get("error") or not r.get("seconds"):
            print(f"    не озвучено: {t['text'][:50]!r}", file=sys.stderr)
        else:
            words[r["id"]] = r.get("words", [])
        bar.update(1)
    bar.close()
    proc.stdin.close()
    proc.wait()
    with open(os.path.join(os.path.dirname(parts), "words.json"), "w") as f:
        json.dump(words, f, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epub", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref-audio", help="референс для клонирования")
    ap.add_argument("--ref-text", help="файл с расшифровкой референса")
    ap.add_argument("--voice", help="пресетный голос вместо клонирования "
                                    "(serena, ryan, eric, vivian, aiden, dylan…)")
    ap.add_argument("--language", default="Russian")
    ap.add_argument("--lang-code", default="ru")
    ap.add_argument("--limit-chunks", type=int, default=None,
                    help="озвучить только первые N чанков главы")
    ap.add_argument("--model", help="модель; по умолчанию берётся из описания движка")
    ap.add_argument("--target", type=int, default=200)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-p", type=float, default=0.8)
    ap.add_argument("--only", type=int, default=None, help="озвучить одну главу")
    ap.add_argument("--engine", default="qwen",
                    choices=("qwen", "apple", "kokoro", "kokoro-ru"),
                    help="движок синтеза")
    ap.add_argument("--rate", type=float, default=None,
                    help="скорость системного голоса (только для apple)")
    ap.add_argument("--batch", type=int, default=8,
                    help="сколько фрагментов Qwen считает за раз; "
                         "больше -- быстрее, но больше памяти")
    args = ap.parse_args()

    os.environ["OVERLAY_ENGINE"] = args.engine
    if not args.model:
        # Модель определяется движком. Раньше здесь стояла Qwen по
        # умолчанию, и Kokoro молча синтезировала ею: голос был чужой, а
        # скорость -- в пятнадцать раз ниже её собственной.
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "engines"))
        from registry import ENGINES
        models = ENGINES.get(args.engine, {}).get("модели") or []
        # Системному голосу модель не нужна: синтезирует сама macOS.
        if models:
            args.model = models[0][0]
        elif args.engine != "apple":
            sys.exit(f"для движка {args.engine} не задана модель")
    if args.engine == "qwen" and not args.voice and not (args.ref_audio and args.ref_text):
        ap.error("нужен либо --voice, либо пара --ref-audio/--ref-text")
    if args.engine == "apple":
        ref_text = None
    else:
        ref_text = (open(args.ref_text, encoding="utf-8").read().strip()
                    if args.ref_text else None)
    parts = os.path.join(args.out, "parts"); os.makedirs(parts, exist_ok=True)
    chapters = extract(args.epub, args.target)
    if args.only is not None:
        chapters = chapters[args.only:args.only + 1]
    if args.limit_chunks:
        for c in chapters:
            c["chunks"] = c["chunks"][:args.limit_chunks]
    json.dump(chapters, open(os.path.join(args.out, "chapters.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"ГЛАВЫ {len(chapters)}", flush=True)
    print(f"глав: {len(chapters)}, чанков: {sum(len(c['chunks']) for c in chapters)}")

    if args.engine == "apple":
        synth_apple(chapters, parts, args.voice, args.rate)
        print("готово")
        return

    if args.engine == "qwen" and args.batch > 1:
        # Пакетом Qwen считает в разы быстрее: веса читаются из памяти один
        # раз на пакет, а не на каждый фрагмент.
        # Помощник запускается интерпретатором своего окружения: там стоит
        # версия mlx-audio с батчингом.
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(here, "engines"))
        from registry import env_python, is_ready
        py = env_python("qwen") if is_ready("qwen") else sys.executable
        helper = os.path.join(here, "engines", "qwen_batch.py")
        cmd = [py, helper, "--out", parts,
               "--model", args.model, "--batch", str(args.batch),
               "--lang-code", args.lang_code,
               "--temperature", str(args.temperature),
               "--top-p", str(args.top_p)]
        if args.ref_audio:
            cmd += ["--ref-audio", args.ref_audio, "--ref-text", args.ref_text]
        if args.voice:
            cmd += ["--voice", args.voice]
        synth_batch(chapters, parts, cmd, "Qwen пакетом")
        print("готово")
        return

    if args.engine == "kokoro-ru":
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "engines", "kokoro_ru.py")
        cmd = [sys.executable, helper, "--out", parts,
               "--voice", args.voice or "sveta"]
        synth_stream(chapters, parts, cmd, "Kokoro русская")
        print("готово")
        return

    if args.engine == "apple":
        synth_apple(chapters, parts, args.voice, args.rate)
        print("готово")
        return

    if args.engine == "qwen" and args.batch > 1:
        # Пакетом Qwen считает в разы быстрее: веса читаются из памяти один
        # раз на пакет, а не на каждый фрагмент.
        # Помощник запускается интерпретатором своего окружения: там стоит
        # версия mlx-audio с батчингом.
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(here, "engines"))
        from registry import env_python, is_ready
        py = env_python("qwen") if is_ready("qwen") else sys.executable
        helper = os.path.join(here, "engines", "qwen_batch.py")
        cmd = [py, helper, "--out", parts,
               "--model", args.model, "--batch", str(args.batch),
               "--lang-code", args.lang_code,
               "--temperature", str(args.temperature),
               "--top-p", str(args.top_p)]
        if args.ref_audio:
            cmd += ["--ref-audio", args.ref_audio, "--ref-text", args.ref_text]
        if args.voice:
            cmd += ["--voice", args.voice]
        synth_batch(chapters, parts, cmd, "Qwen пакетом")
        print("готово")
        return

    if args.engine == "kokoro-ru":
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "engines", "kokoro_ru.py")
        cmd = [sys.executable, helper, "--out", parts,
               "--voice", args.voice or "sveta"]
        synth_stream(chapters, parts, cmd, "Kokoro русская")
        print("готово")
        return

    tasks = []
    for ci, ch in enumerate(chapters):
        for i, t in enumerate(ch["chunks"]):
            tasks.append((t, os.path.join(parts, f"{ci:04d}_{i:04d}.wav"),
                          args.temperature, args.top_p))
    todo = [t for t in tasks if not os.path.exists(t[1])]
    print(f"к синтезу: {len(todo)} (готово: {len(tasks)-len(todo)})")

    # Kokoro синтезирует в десятки раз быстрее реального времени, и на её
    # фоне загрузка модели в каждый воркер дороже самой работы: пул из трёх
    # процессов делает прогон медленнее, а не быстрее.
    if args.engine.startswith("kokoro"):
        args.workers = 1

    if todo:
        # Рабочие не должны переживать своего родителя: если прогон убит,
        # пул уходит вместе с ним, а не остаётся сиротой на GPU.
        import atexit, signal as _sig
        def _reap(*_):
            for c in mp.active_children():
                c.terminate()
            sys.exit(130)
        _sig.signal(_sig.SIGTERM, _reap)
        _sig.signal(_sig.SIGINT, _reap)
        atexit.register(lambda: [c.terminate() for c in mp.active_children()])

        with mp.Pool(args.workers, initializer=init,
                     initargs=(args.model, args.ref_audio, ref_text,
                               args.voice, args.language, args.lang_code)) as pool:
            from tqdm import tqdm
            # imap (не unordered): фрагменты идут по порядку глав, иначе
            # «глава 3 из 40» ничего не значит
            bar = tqdm(pool.imap(synth, todo), total=len(todo),
                       unit="чанк", ncols=88, smoothing=0.05,
                       bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} "
                                  "[{elapsed}<{remaining}, {rate_fmt}]")
            failed, seen = 0, -1
            for k, r in enumerate(bar):
                if r is None:
                    failed += 1
                    bar.set_postfix_str(f"сбоев: {failed}")
                ci = int(os.path.basename(todo[k][1]).split("_")[0])
                if ci != seen:
                    seen = ci
                    print(f"ГЛАВА {ci + 1} {chapters[ci]['title'][:60]}", flush=True)
            bar.close()
            if failed:
                print(f"не озвучено чанков: {failed}", file=sys.stderr)
    print("готово")


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
