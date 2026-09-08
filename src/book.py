"""Книга на входе — EPUB с media overlay на выходе.

Язык определяется по самой книге, референс подбирается под язык, правка
mlx-audio применяется сама. Никаких обязательных настроек: всё, что можно
вывести из книги, выводится из неё.

Прогресс печатается строками вида `ПРОГРЕСС n/N`, чтобы поверх можно было
надеть интерфейс.
"""
import argparse, json, os, re, subprocess, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
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
    return {"референсы": refs, "пресеты": PRESETS, "система": apple}
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
    args = ap.parse_args()

    if args.list_voices:
        for group, names in available_voices().items():
            print(f"{group}: {', '.join(names)}")
        return

    if not args.book:
        ap.error("не указана книга")
    book = os.path.abspath(args.book)
    if not os.path.exists(book):
        sys.exit(f"нет такого файла: {book}")

    lang, how = (args.language, "задан вручную") if args.language else detect_language(book)
    if lang not in REFERENCE:
        sys.exit(f"язык {lang!r} пока не поддержан; есть: {', '.join(REFERENCE)}")
    spoken, code = SPOKEN[lang]

    apple = (args.voice[len("apple:"):].split("|")[0]
             if (args.voice or "").startswith("apple:") else None)
    preset = args.voice if args.voice in PRESETS else None
    ref = None
    if not preset and not apple:
        name = args.voice or REFERENCE[lang]
        ref = os.path.join(REFS, name)
        if not (os.path.exists(ref + ".wav") and os.path.exists(ref + ".txt")):
            sys.exit(f"нет такого голоса: {name}\n"
                     f"доступные: {available_voices()}")

    work = args.out or os.path.join(ROOT, "out", slug(book))
    final = args.epub_out or os.path.join(ROOT, "out", slug(book) + "_overlay.epub")
    os.makedirs(work, exist_ok=True)

    model = args.model or (CUSTOM_VOICE_MODEL if preset else None)
    print(f"книга:    {os.path.basename(book)}")
    print(f"язык:     {lang}  ({how})")
    if apple:
        print(f"голос:    {apple.split('.')[-1]} (системный, подсветка по словам)")
    else:
        print(f"голос:    {preset + ' (пресет)' if preset else os.path.basename(ref)}")
    if abs(args.speed - 1.0) > 1e-3:
        print(f"темп:     {args.speed}x")
    if apple:
        print("правка:   не нужна, системный синтез")
    else:
        print(f"правка:   {ensure_patch(args.python) if not preset else 'не нужна для пресетов'}")
    print(f"результат: {final}\n", flush=True)

    narrate = [args.python, os.path.join(HERE, "narrate.py"),
               "--epub", book, "--out", work,
               "--language", spoken, "--lang-code", code,
               "--workers", str(args.workers)]
    if apple:
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
    if subprocess.run(narrate).returncode != 0:
        sys.exit("синтез прерван")

    title = os.path.splitext(os.path.basename(book))[0][:70]
    mo = [args.python, os.path.join(HERE, "mo.py"), "--out", work,
          "--epub", final, "--title", title, "--lang", code,
          "--speed", str(args.speed)]
    if subprocess.run(mo).returncode != 0:
        sys.exit("сборка EPUB прервана")

    manifest = os.path.join(work, "manifest.json")
    json.dump({"книга": book, "язык": lang, "определён": how,
               "голос": apple or preset or os.path.basename(ref), "темп": args.speed,
               "модель": model or "по умолчанию", "результат": final,
               "команды": [" ".join(narrate), " ".join(mo)]},
              open(manifest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nготово: {final}")


if __name__ == "__main__":
    main()
