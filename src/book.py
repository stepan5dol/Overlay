"""Книга на входе — EPUB с media overlay на выходе.

Язык определяется по самой книге, референс подбирается под язык, правка
mlx-audio применяется сама. Никаких обязательных настроек: всё, что можно
вывести из книги, выводится из неё.

Прогресс печатается строками вида `ПРОГРЕСС n/N`, чтобы поверх можно было
надеть интерфейс.
"""
import argparse, json, os, re, signal, subprocess, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import state as st
ROOT = os.path.dirname(HERE)
REFS = os.path.join(ROOT, "refs")

REFERENCE = {                       # язык -> голос по умолчанию, пара wav/txt в refs/
    "ru": "vakhshtayn",
    "en": "linda_johnson",
}
# Пресеты озвучиваются моделью CustomVoice: ей референс не нужен, но и
# клонировать она не умеет -- это другой путь генерации.
CUSTOM_VOICE_MODEL = "/Users/stepandolzhenko/qwen3-tts-apple-silicon/qwen3-tts-patched"
PRESETS = ["serena", "vivian", "uncle_fu", "ryan", "aiden",
           "ono_anna", "sohee", "eric", "dylan"]


KOKORO_LANG = {"a": "американский", "b": "британский"}


def kokoro_voices():
    """Голоса Kokoro: имя кодирует язык и пол (af_ -- amer. female и т.д.)."""
    import sys as _s
    _s.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "engines"))
    from registry import ENGINES, is_ready
    out = []
    for eng in ("kokoro", "kokoro-ru"):
        if not is_ready(eng):
            continue
        try:
            from huggingface_hub import list_repo_files
            repo = ENGINES[eng]["модели"][0][0]
            names = sorted({f.split("/")[-1].replace(".pt", "")
                            for f in list_repo_files(repo)
                            if f.startswith("voices/") and f.endswith(".pt")})
        except Exception:
            continue
        for n in names:
            if eng == "kokoro" and n[:1] not in "ab":
                continue                      # прочие языки конвейер не ведёт
            out.append(f"{eng}:{n}")
    return out


    return out


def apple_voices(lang=None):
    """Голоса системы. Хорошие (enhanced/premium) пользователь скачивает сам."""
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    binary = os.path.join(os.path.dirname(here), "app", "appletts")
    if not os.path.exists(binary):
        return []
    try:
        out = subprocess.run([binary, "--list"], capture_output=True,
                             text=True, timeout=20).stdout
        vs = json.loads(out)
    except Exception:
        return []
    # только современный набор: com.apple.speech.synthesis.* -- это старые
    # шуточные голоса (Bad News, Boing, Bubbles), для книги непригодные,
    # com.apple.eloquence.* -- ретро-синтез восьмидесятых.
    vs = [v for v in vs if v["identifier"].startswith("com.apple.voice.")
          and ".super-compact." not in v["identifier"]]
    if lang:
        vs = [v for v in vs if v["language"].lower().startswith(lang)]
    # хорошие вперёд: их и стоит выбирать
    order = {"premium": 0, "enhanced": 1, "compact": 2}
    vs.sort(key=lambda v: (order.get(v["quality"], 3), v["name"]))
    return vs


def available_voices():
    """Три источника голоса: образцы для клонирования, пресеты, система."""
    refs = sorted(n[:-4] for n in os.listdir(REFS)
                  if n.endswith(".wav") and os.path.exists(
                      os.path.join(REFS, n[:-4] + ".txt")))
    # только языки, которые конвейер поддерживает, иначе список в сотню строк
    apple = [f"apple:{v['identifier']}|{v['name']} · {v['language']} · {v['quality']}"
             for v in apple_voices()
             if v["language"][:2] in REFERENCE]
    kok = []
    for v in kokoro_voices():
        eng, name = v.split(":", 1)
        if eng == "kokoro-ru":
            label = f"{name} · русский"
        else:
            lang = KOKORO_LANG.get(name[:1], "")
            sex = "жен." if name[1:2] == "f" else "муж."
            label = f"{name[3:]} · {lang} · {sex}"
        kok.append(f"{v}|{label}")
    return {"референсы": refs, "пресеты": PRESETS, "система": apple,
            "быстрые": kok}
SPOKEN = {"ru": ("Russian", "ru"), "en": ("English", "en")}


def detect_language(epub_path):
    """Язык из метаданных книги, а при их отсутствии — по доле кириллицы."""
    import ebooklib
    from ebooklib import epub
    book = epub.read_epub(epub_path)
    for _, value in (book.get_metadata("DC", "language") or [("", "")]):
        code = (value or "").strip().lower()[:2] if isinstance(value, str) else ""
        if code in REFERENCE:
            return code, "метаданные книги"
    sys.path.insert(0, HERE)
    from narrate import chapter_text
    text = ""
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        text += " ".join(chapter_text(item.get_content()))
        if len(text) > 4000:
            break
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en", "по умолчанию (текста не нашлось)"
    cyr = sum("CYRILLIC" in unicodedata.name(c, "") for c in letters)
    share = cyr / len(letters)
    return ("ru" if share > 0.3 else "en"), f"по тексту, кириллицы {share:.0%}"


def ensure_patch(python):
    """ICL включается правкой загрузчика mlx-audio; применяем, если её нет."""
    sp = subprocess.run(
        [python, "-c", "import mlx_audio, os; print(os.path.dirname(os.path.dirname(mlx_audio.__file__)))"],
        capture_output=True, text=True).stdout.strip()
    if not sp:
        sys.exit("не найден mlx_audio в выбранном python")
    target = os.path.join(sp, "mlx_audio/tts/models/qwen3_tts/qwen3_tts.py")
    if "Qwen3TTSTokenizerEncoderConfig(**filtered)" in open(target).read():
        return "уже применена"
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "patches", "enable_icl_encoder.py"), sp],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("не удалось применить правку mlx-audio:\n" + r.stderr)
    return "применена сейчас"


def own_process_group():
    """Прогон живёт в своей группе процессов.

    Группу открывает сам прогон, а его шаги остаются внутри неё. Тогда
    сигнал по группе гасит всю цепочку -- посредника, синтез и рабочих, --
    а соседние прогоны, у которых группы свои, этого не замечают.
    """
    try:
        os.setpgrp()
    except OSError:
        pass


def run_stage(cmd, name):
    """Запуск шага в той же группе процессов, что и сам прогон.

    Группу открывает окно -- один раз на прогон. Тогда кнопка «Остановить»
    гасит всю цепочку целиком, а соседние прогоны, живущие в своих группах,
    этого не замечают. Отдельная группа на каждый шаг делала синтез
    неубиваемым: посредник умирал, а он оставался сиротой.
    """
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
    хвост = []
    import threading

    def слушать():
        for line in proc.stderr:
            хвост.append(line)
            del хвост[:-40]
            sys.stderr.write(line)
    t = threading.Thread(target=слушать, daemon=True)
    t.start()
    try:
        code = proc.wait()
        t.join(timeout=2)
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        sys.exit(f"{name}: остановлено")
    if code != 0:
        # Внятная строка для окна: без неё человек видит только «прервалось»
        # и идёт читать журнал.
        причина = ""
        for line in reversed(хвост):
            line = line.strip()
            if line.startswith(("RuntimeError:", "FileNotFoundError:",
                                "ValueError:", "OSError:")):
                причина = line.split(":", 1)[1].strip()
                break
            if line.startswith("не найден") or line.startswith("не удалось"):
                причина = line
                break
        print(f"СБОЙ {name}: {причина or f'код {code}'}", flush=True)
        sys.exit(1)


def каталог_фрагментов(work):
    return os.path.join(work, "parts")


def превратить_pdf(pdf, python_по_умолчанию):
    """PDF -> EPUB, дальше книга идёт обычным путём.

    Разбор делает docling в своём окружении: он размечает страницу и
    отделяет колонтитулы от текста. Готовый EPUB кладётся рядом с
    рабочими файлами и переиспользуется при повторном запуске.
    """
    sys.path.insert(0, os.path.join(HERE, "engines"))
    from registry import env_python, is_ready

    if not is_ready("docling"):
        print("ЭТАП ставлю разборщик PDF", flush=True)
        код = subprocess.call([sys.executable,
                               os.path.join(HERE, "engines", "install.py"),
                               "docling"])
        if код != 0:
            sys.exit("не удалось поставить разборщик PDF")

    готовый = os.path.join(ROOT, "out", slug(pdf) + "__из_pdf.epub")
    os.makedirs(os.path.dirname(готовый), exist_ok=True)
    if os.path.exists(готовый) and os.path.getmtime(готовый) > os.path.getmtime(pdf):
        print(f"беру уже разобранный PDF: {os.path.basename(готовый)}", flush=True)
        return готовый

    print("ЭТАП разбираю PDF", flush=True)
    код = subprocess.call([env_python("docling"),
                           os.path.join(HERE, "engines", "pdf2epub.py"), pdf,
                           "--out", готовый])
    if код != 0:
        sys.exit("не удалось разобрать PDF")
    return готовый


def sha_of(path, limit=1 << 20):
    """Короткий отпечаток книги: чтобы правка исходника не смешалась
    со старой озвучкой."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(limit))
    return h.hexdigest()[:16]


def slug(path):
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"\s*\([^)]*\)", "", name)
    return re.sub(r"[^\w-]+", "_", name, flags=re.U).strip("_")[:60] or "book"


def main():
    ap = argparse.ArgumentParser(description="EPUB -> EPUB с синхронной озвучкой")
    ap.add_argument("book", nargs="?", help="путь к .epub")
    ap.add_argument("--out", help="каталог для работы (по умолчанию out/<имя>)")
    ap.add_argument("--epub-out", help="итоговый файл (по умолчанию рядом с out)")
    ap.add_argument("--only", type=int, help="озвучить одну главу по номеру")
    ap.add_argument("--limit-chunks", type=int, help="ограничить число фрагментов")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--python", default=sys.executable,
                    help="python с mlx-audio")
    ap.add_argument("--language", help="ru или en, если определять не нужно")
    ap.add_argument("--voice", help="имя референса из refs/ или пресет CustomVoice")
    ap.add_argument("--model", help="путь или идентификатор модели")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="темп речи, применяется после синтеза")
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument("--format", default="epub", choices=("epub", "m4b", "both"),
                    help="epub с подсветкой, аудиокнига m4b, или оба")
    ap.add_argument("--dest", help="куда положить результат")
    ap.add_argument("--keep-work", action="store_true",
                    help="не удалять промежуточные файлы после сборки")
    args = ap.parse_args()

    if args.list_voices:
        for group, names in available_voices().items():
            print(f"{group}: {', '.join(names)}")
        return

    if not args.book:
        ap.error("не указана книга")
    own_process_group()
    book = os.path.abspath(args.book)
    if not os.path.exists(book):
        sys.exit(f"нет такого файла: {book}")

    исходный_pdf = None
    if book.lower().endswith(".pdf"):
        исходный_pdf = book
        book = превратить_pdf(book, args.python)

    lang, how = (args.language, "задан вручную") if args.language else detect_language(book)
    if lang not in REFERENCE:
        sys.exit(f"язык {lang!r} пока не поддержан; есть: {', '.join(REFERENCE)}")
    spoken, code = SPOKEN[lang]

    apple = (args.voice[len("apple:"):].split("|")[0]
             if (args.voice or "").startswith("apple:") else None)
    kokoro = None
    if (args.voice or "").startswith(("kokoro:", "kokoro-ru:")):
        eng, name = args.voice.split("|")[0].split(":", 1)
        kokoro = (eng, name)
    preset = args.voice if args.voice in PRESETS else None
    ref = None
    if not preset and not apple and not kokoro:
        name = args.voice or REFERENCE[lang]
        ref = os.path.join(REFS, name)
        if not (os.path.exists(ref + ".wav") and os.path.exists(ref + ".txt")):
            sys.exit(f"нет такого голоса: {name}\n"
                     f"доступные: {available_voices()}")

    # В имя рабочей папки входит голос и темп: фрагменты кэшируются, и без
    # этого прогон другим голосом молча подхватил бы чужую озвучку.
    voice_tag = re.sub(r"[^\w.-]+", "_",
                       (args.voice or REFERENCE[lang]).replace(":", "-"))
    if abs(args.speed - 1.0) > 1e-3:
        voice_tag += f"@{args.speed:g}"
    work = args.out or os.path.join(ROOT, "out", f"{slug(book)}__{voice_tag}")
    dest = args.dest or os.path.expanduser("~/Documents")
    os.makedirs(dest, exist_ok=True)
    stem = f"{slug(book)}__{voice_tag}"
    final = args.epub_out or os.path.join(dest, stem + "_overlay.epub")
    m4b = os.path.join(dest, stem + ".m4b")
    os.makedirs(work, exist_ok=True)
    отпечаток = {"голос": args.voice or REFERENCE[lang], "язык": lang,
                 "темп": args.speed, "книга": sha_of(book)}
    прежний = st.load(work)
    if прежний and прежний.get("отпечаток") != отпечаток:
        import shutil
        print(f"прежняя работа не подходит ({прежний.get('отпечаток', {}).get('голос')}), "
              f"начинаю заново", flush=True)
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work, exist_ok=True)
    elif прежний and not прежний.get("завершён"):
        сделано = прежний.get("фрагментов_готово", 0)
        print(f"ПРОДОЛЖАЮ прерванный прогон: этап «{прежний.get('этап')}»"
              + (f", фрагментов готово {сделано}" if сделано else ""), flush=True)
    st.save(work, отпечаток=отпечаток, завершён=False, этап="извлечение")

    model = args.model or (CUSTOM_VOICE_MODEL if preset else None)
    print(f"книга:    {os.path.basename(book)}")
    print(f"язык:     {lang}  ({how})")
    if kokoro:
        print(f"голос:    {kokoro[1]} ({kokoro[0]}, быстрый синтез)")
    elif apple:
        print(f"голос:    {apple.split('.')[-1]} (системный, подсветка по словам)")
    else:
        print(f"голос:    {preset + ' (пресет)' if preset else os.path.basename(ref)}")
    if abs(args.speed - 1.0) > 1e-3:
        print(f"темп:     {args.speed}x")
    if apple or kokoro:
        print("правка:   не нужна")
    else:
        print(f"правка:   {ensure_patch(args.python) if not preset else 'не нужна для пресетов'}")
    print(f"папка:    {dest}")
    print(f"результат: {'аудиокнига и EPUB' if args.format == 'both' else ('аудиокнига' if args.format == 'm4b' else 'EPUB с подсветкой')}\n",
          flush=True)

    engine_py = args.python
    if kokoro:
        sys.path.insert(0, os.path.join(HERE, "engines"))
        from registry import env_python, is_ready
        if not is_ready(kokoro[0]):
            sys.exit(f"движок {kokoro[0]} не установлен: "
                     f"python3 src/engines/install.py {kokoro[0]}")
        engine_py = env_python(kokoro[0])

    narrate = [engine_py, os.path.join(HERE, "narrate.py"),
               "--epub", book, "--out", work,
               "--language", spoken, "--lang-code", code,
               "--workers", str(args.workers)]
    if kokoro:
        eng, name = kokoro
        narrate += ["--engine", eng, "--voice", name]
        if eng == "kokoro":
            narrate += ["--lang-code", "a"]
    elif apple:
        narrate += ["--engine", "apple", "--voice", apple]
    elif preset:
        narrate += ["--voice", preset]
    else:
        narrate += ["--ref-audio", ref + ".wav", "--ref-text", ref + ".txt"]
    if model and not apple:
        narrate += ["--model", model]
    if args.only is not None:
        narrate += ["--only", str(args.only)]
    if args.limit_chunks:
        narrate += ["--limit-chunks", str(args.limit_chunks)]
    st.save(work, этап="синтез")
    run_stage(narrate, "синтез")
    st.save(work, этап="сборка",
            фрагментов_готово=len([n for n in os.listdir(каталог_фрагментов(work))
                                   if n.endswith(".wav")]))
    print("ЭТАП сборка", flush=True)

    title = os.path.splitext(os.path.basename(book))[0][:70]
    produced, commands = [], [" ".join(narrate)]

    if args.format in ("epub", "both"):
        print("ЭТАП сборка книги с подсветкой", flush=True)
        # mo2 добавляет озвучку в исходную книгу, сохраняя вёрстку,
        # картинки и стили; mo строил EPUB с нуля и терял их.
        mo = [args.python, os.path.join(HERE, "mo2.py"), "--out", work,
              "--source", book, "--epub", final, "--speed", str(args.speed)]
        run_stage(mo, "сборка EPUB")
        commands.append(" ".join(mo))
        produced.append(final)

    if args.format in ("m4b", "both"):
        print("ЭТАП сборка аудиокниги", flush=True)
        asm = [args.python, os.path.join(HERE, "assemble.py"), "--out", work,
               "--title", title, "--m4b"]
        run_stage(asm, "сборка аудиокниги")
        commands.append(" ".join(asm))
        built = os.path.join(work, "audiobook.m4b")
        if os.path.exists(built):
            os.replace(built, m4b)
            produced.append(m4b)

    manifest = os.path.join(work, "manifest.json")
    json.dump({"книга": book, "язык": lang, "определён": how, "формат": args.format,
               "голос": (kokoro[1] if kokoro else
                         (apple or preset or os.path.basename(ref))),
               "темп": args.speed,
               "модель": model or "по умолчанию", "результат": produced,
               "команды": commands,
               "исходный_pdf": исходный_pdf},
              open(manifest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    stats = {}
    try:
        chs = json.load(open(os.path.join(work, "chapters.json")))
        stats["главы"] = len(chs)
        stats["фрагменты"] = sum(len(c["chunks"]) for c in chs)
        stats["слова"] = sum(len(x.split()) for c in chs for x in c["chunks"])
        # wave из стандартной библиотеки не читает float-WAV, который
        # пишет синтез, поэтому длительность берём через soundfile.
        import soundfile as sf
        parts_dir = os.path.join(work, "parts")
        total = sum(sf.info(os.path.join(parts_dir, n)).duration
                    for n in os.listdir(parts_dir) if n.endswith(".wav"))
        stats["секунды"] = round(total / max(args.speed, 0.01), 1)
        stats["байты"] = sum(os.path.getsize(f) for f in produced
                             if os.path.exists(f))
    except Exception as e:
        print(f"статистика неполна: {e}", file=sys.stderr)
    if stats:
        print("СТАТИСТИКА " + json.dumps(stats, ensure_ascii=False), flush=True)
    st.save(work, этап="готово", завершён=True, результат=produced)

    # Промежуточные файлы после успеха не нужны: фрагменты книги весят
    # столько же, сколько сама книга, и копятся с каждым прогоном. Каталог
    # сносится целиком -- незаконченная работа сюда не попадает, у неё
    # завершён=False, и она доживает до следующего запуска.
    if produced and not args.keep_work:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    for f in produced:
        print(f"готово: {f}")


if __name__ == "__main__":
    main()
