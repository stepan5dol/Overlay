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

REFERENCE = {                       # язык -> имя пары wav/txt в refs/
    "ru": "ru_female",
    "en": "en_female_ljspeech",
}
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
    ap.add_argument("book", help="путь к .epub")
    ap.add_argument("--out", help="каталог для работы (по умолчанию out/<имя>)")
    ap.add_argument("--epub-out", help="итоговый файл (по умолчанию рядом с out)")
    ap.add_argument("--only", type=int, help="озвучить одну главу по номеру")
    ap.add_argument("--limit-chunks", type=int, help="ограничить число фрагментов")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--python", default=sys.executable,
                    help="python с mlx-audio")
    ap.add_argument("--language", help="ru или en, если определять не нужно")
    args = ap.parse_args()

    book = os.path.abspath(args.book)
    if not os.path.exists(book):
        sys.exit(f"нет такого файла: {book}")

    lang, how = (args.language, "задан вручную") if args.language else detect_language(book)
    if lang not in REFERENCE:
        sys.exit(f"язык {lang!r} пока не поддержан; есть: {', '.join(REFERENCE)}")
    spoken, code = SPOKEN[lang]
    ref = os.path.join(REFS, REFERENCE[lang])
    if not (os.path.exists(ref + ".wav") and os.path.exists(ref + ".txt")):
        sys.exit(f"нет референса для языка {lang}: {ref}.wav/.txt")

    work = args.out or os.path.join(ROOT, "out", slug(book))
    final = args.epub_out or os.path.join(ROOT, "out", slug(book) + "_overlay.epub")
    os.makedirs(work, exist_ok=True)

    print(f"книга:    {os.path.basename(book)}")
    print(f"язык:     {lang}  ({how})")
    print(f"голос:    {REFERENCE[lang]}")
    print(f"правка:   {ensure_patch(args.python)}")
    print(f"результат: {final}\n", flush=True)

    narrate = [args.python, os.path.join(HERE, "narrate.py"),
               "--epub", book, "--out", work,
               "--ref-audio", ref + ".wav", "--ref-text", ref + ".txt",
               "--language", spoken, "--lang-code", code,
               "--workers", str(args.workers)]
    if args.only is not None:
        narrate += ["--only", str(args.only)]
    if args.limit_chunks:
        narrate += ["--limit-chunks", str(args.limit_chunks)]
    if subprocess.run(narrate).returncode != 0:
        sys.exit("синтез прерван")

    title = os.path.splitext(os.path.basename(book))[0][:70]
    mo = [args.python, os.path.join(HERE, "mo.py"), "--out", work,
          "--epub", final, "--title", title, "--lang", code]
    if subprocess.run(mo).returncode != 0:
        sys.exit("сборка EPUB прервана")

    manifest = os.path.join(work, "manifest.json")
    json.dump({"книга": book, "язык": lang, "определён": how,
               "референс": REFERENCE[lang], "результат": final,
               "команды": [" ".join(narrate), " ".join(mo)]},
              open(manifest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nготово: {final}")


if __name__ == "__main__":
    main()
