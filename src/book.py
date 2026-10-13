"""Книга на входе — EPUB с media overlay на выходе."""
import argparse, json, os, re, signal, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import state as st
from ui import т

# Рабочие файлы -- в каталоге данных пользователя, а не рядом с кодом:
# приложение живёт в /Applications, куда писать нельзя, и прогоны попадали
# внутрь бандла, пропадая при первой же переустановке.
РАБОЧИЙ = os.path.expanduser("~/Library/Application Support/Overlay/work")
ROOT = os.path.dirname(HERE)
REFS = os.path.join(ROOT, "refs")

ЯЗЫКИ = ("ru", "en")
# Пресеты озвучиваются моделью CustomVoice: ей референс не нужен, но и
# клонировать она не умеет -- это другой путь генерации.
# Модель для пресетных голосов. Берётся из кэша HuggingFace, а не из
# локальной папки: путь к чужому каталогу работал только на одной машине.
CUSTOM_VOICE_MODEL = os.environ.get(
    "OVERLAY_CUSTOM_VOICE_MODEL",
    "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit")
PRESETS = ["serena", "vivian", "uncle_fu", "ryan", "aiden",
           "ono_anna", "sohee", "eric", "dylan"]


KOKORO_LANG = {"a": "американский", "b": "британский"}

# Голоса, которые появятся после установки движка. Нужны, чтобы список не
# был пустым у того, кто ещё ничего не скачал.
ИЗВЕСТНЫЕ_ГОЛОСА = {
    "kokoro": ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky",
               "am_adam", "am_michael", "am_onyx", "am_puck",
               "bf_emma", "bf_isabella", "bm_george", "bm_lewis"],
    "kokoro-ru": ["sveta", "masha", "dima"],
}


def kokoro_voices():
    """Голоса Kokoro: имя кодирует язык и пол (af_ -- amer. female и т.д.)."""
    import sys as _s
    _s.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "engines"))
    from registry import ENGINES, is_ready
    out = []
    for eng in ("kokoro", "kokoro-ru"):
        # Голоса показываем и до установки движка: иначе у нового человека
        # выбирать не из чего, и непонятно, что вообще можно скачать.
        if not is_ready(eng):
            имена = ИЗВЕСТНЫЕ_ГОЛОСА.get(eng, [])
            out.extend(f"{eng}:{n}" for n in имена)
            continue
        try:
            from huggingface_hub import list_repo_files
            repo = ENGINES[eng]["модели"][0][0]
            names = sorted({f.split("/")[-1].replace(".pt", "")
                            for f in list_repo_files(repo)
                            if f.startswith("voices/") and f.endswith(".pt")})
        except Exception:
            # Список из сети недоступен (нет huggingface_hub в служебном
            # интерпретаторе, нет сети) -- берём известные имена.
            names = ИЗВЕСТНЫЕ_ГОЛОСА.get(eng, [])
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
    root = os.path.dirname(here)
    # Внутри бандла помощник лежит рядом с src/, при разработке -- в app/
    for binary in (os.path.join(root, "appletts"),
                   os.path.join(root, "app", "appletts")):
        if os.path.exists(binary):
            break
    else:
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


# Язык образца определяется по имени файла в refs/README.md; проще и
# надёжнее держать его тут, пока образцов немного.
ЯЗЫК_ОБРАЗЦА = {
    "vakhshtayn": "ru",
    "linda_johnson": "en",
    "bryan_ness": "en",
    "meredith_hughes": "en",
}


def available_voices():
    """Три источника голоса: образцы для клонирования, пресеты, система.

    К каждому голосу приписан язык -- окно показывает только подходящие
    выбранному языку книги.
    """
    refs = sorted(n[:-4] for n in os.listdir(REFS)
                  if n.endswith(".wav") and os.path.exists(
                      os.path.join(REFS, n[:-4] + ".txt")))
    # только языки, которые конвейер поддерживает, иначе список в сотню строк
    apple = [f"apple:{v['identifier']}|{v['name']} · {v['language']} · "
             f"{v['quality']}|{v['language'][:2]}"
             for v in apple_voices()
             if v["language"][:2] in ЯЗЫКИ]
    kok = []
    for v in kokoro_voices():
        eng, name = v.split(":", 1)
        if eng == "kokoro-ru":
            label, язык = f"{name} · {т('русский')}", "ru"
        else:
            lang = т(KOKORO_LANG.get(name[:1], ""))
            sex = т("жен." if name[1:2] == "f" else "муж.")
            label, язык = f"{name[3:]} · {lang} · {sex}", "en"
        kok.append(f"{v}|{label}|{язык}")

    рефы = [f"{n}|{n}|{ЯЗЫК_ОБРАЗЦА.get(n, '')}" for n in refs]
    # Пресеты Qwen многоязычные -- показываем всегда.
    пресеты = [f"{n}|{n}|" for n in PRESETS]
    return {"референсы": рефы, "пресеты": пресеты, "система": apple,
            "быстрые": kok}
SPOKEN = {"ru": ("Russian", "ru"), "en": ("English", "en")}


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
        sys.exit(т("{этап}: остановлено", этап=т(name)))
    if code != 0:
        # Внятная строка для окна: без неё человек видит только «прервалось»
        # и идёт читать журнал.
        причина = ""
        for line in reversed(хвост):
            line = line.rstrip()
            if (not line or line.startswith((" ", "\t", "Traceback"))
                    or ("%|" in line and "it" in line)):
                continue
            m = re.match(r"^[\w.]*(?:Error|Exception)\w*: (.+)$", line)
            причина = m.group(1) if m else line
            break
        print(f"СБОЙ {т(name)}: {причина or т('код {код}', код=code)}", flush=True)
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
        print("ЭТАП " + т("ставлю разборщик PDF"), flush=True)
        код = subprocess.call([sys.executable,
                               os.path.join(HERE, "engines", "install.py"),
                               "docling"])
        if код != 0:
            sys.exit(т("не удалось поставить разборщик PDF"))

    # ocrmac -- мост к Vision для сканов -- вошёл в описание docling позже,
    # чем у людей появилось окружение, поэтому доставляется отдельно. Не
    # встал -- не беда: книгам с текстовым слоем он не нужен.
    if subprocess.call([env_python("docling"), "-c",
                        "import importlib.util as u, sys; "
                        "sys.exit(u.find_spec('ocrmac') is None)"]) != 0:
        print("ЭТАП " + т("ставлю распознавание сканов"), flush=True)
        subprocess.call([env_python("docling"), "-m", "pip", "install", "-q",
                         "--disable-pip-version-check", "ocrmac"])

    готовый = os.path.join(РАБОЧИЙ, slug(pdf) + "__из_pdf.epub")
    os.makedirs(os.path.dirname(готовый), exist_ok=True)
    if (os.path.exists(готовый) and os.path.getmtime(готовый) > os.path.getmtime(pdf)
            and есть_текст(готовый)):
        print(т("беру уже разобранный PDF: {имя}", имя=os.path.basename(готовый)), flush=True)
        return готовый

    print("ЭТАП " + т("разбираю PDF"), flush=True)
    код = subprocess.call([env_python("docling"),
                           os.path.join(HERE, "engines", "pdf2epub.py"), pdf,
                           "--out", готовый])
    if код == 3:                        # pdf2epub.НЕТ_ТЕКСТА
        sys.exit(т("в PDF нет текста, и распознать его не удалось"))
    if код != 0:
        sys.exit(т("не удалось разобрать PDF"))
    return готовый


def есть_текст(epub):
    """Есть ли в разобранном PDF хоть один абзац.

    Сканы до появления распознавания разбирались в книгу из одних картинок,
    и такой кэш надо разобрать заново, а не озвучивать пустоту.
    """
    import zipfile
    try:
        with zipfile.ZipFile(epub) as z:
            return any(re.search(rb"<(p|li|h1)[ >]", z.read(n))
                       for n in z.namelist()
                       if "/text/" in n and n.endswith(".xhtml"))
    except zipfile.BadZipFile:
        return False


def sha_of(path, limit=1 << 20):
    """Короткий отпечаток книги: чтобы правка исходника не смешалась
    со старой озвучкой."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(limit))
    return h.hexdigest()[:16]


def длительность_wav(путь):
    import struct
    with open(путь, "rb") as f:
        if f.read(12)[8:12] != b"WAVE":
            return 0.0
        в_секунду = 0
        while True:
            заголовок = f.read(8)
            if len(заголовок) < 8:
                return 0.0
            имя, размер = заголовок[:4], struct.unpack("<I", заголовок[4:])[0]
            if имя == b"data":
                return размер / в_секунду if в_секунду else 0.0
            данные = f.read(размер + (размер & 1))
            if имя == b"fmt ":
                в_секунду = struct.unpack("<I", данные[8:12])[0]


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
    ap.add_argument("--language", choices=ЯЗЫКИ, help="язык книги")
    ap.add_argument("--voice", help="голос из --list-voices")
    ap.add_argument("--model", help="путь или идентификатор модели")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="темп речи, применяется после синтеза")
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument("--format", default="epub", choices=("epub", "m4b", "both"),
                    help="epub с подсветкой, аудиокнига m4b, или оба")
    ap.add_argument("--dest", help="куда положить результат")
    ap.add_argument("--batch", type=int, default=8,
                    help="фрагментов за раз для Qwen (1 -- по одному)")
    ap.add_argument("--keep-work", action="store_true",
                    help="не удалять промежуточные файлы после сборки")
    args = ap.parse_args()

    if args.list_voices:
        for group, names in available_voices().items():
            print(f"{group}: {', '.join(names)}")
        return

    if not args.book or not args.language or not args.voice:
        ap.error("нужны книга, --language и --voice")
    own_process_group()
    book = os.path.abspath(args.book)
    if not os.path.exists(book):
        sys.exit(т("нет такого файла: {путь}", путь=book))

    исходный_pdf = None
    if book.lower().endswith(".pdf"):
        исходный_pdf = book
        book = превратить_pdf(book, args.python)

    lang = args.language
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
        ref = os.path.join(REFS, args.voice)
        if not (os.path.exists(ref + ".wav") and os.path.exists(ref + ".txt")):
            sys.exit(т("нет такого голоса: {имя}", имя=args.voice))

    # В имя рабочей папки входит голос и темп: фрагменты кэшируются, и без
    # этого прогон другим голосом молча подхватил бы чужую озвучку.
    voice_tag = re.sub(r"[^\w.-]+", "_",
                       args.voice.replace(":", "-"))
    if abs(args.speed - 1.0) > 1e-3:
        voice_tag += f"@{args.speed:g}"
    work = args.out or os.path.join(РАБОЧИЙ, f"{slug(book)}__{voice_tag}")
    dest = args.dest or os.path.expanduser("~/Documents")
    os.makedirs(dest, exist_ok=True)
    stem = f"{slug(book)}__{voice_tag}"
    final = args.epub_out or os.path.join(dest, stem + "_overlay.epub")
    m4b = os.path.join(dest, stem + ".m4b")
    os.makedirs(work, exist_ok=True)
    отпечаток = {"голос": args.voice, "язык": lang,
                 "темп": args.speed, "книга": sha_of(book)}
    # Пакетный синтез прежних версий терял образец голоса: фрагменты тех
    # прогонов озвучены чужим голосом, продолжать поверх них нельзя.
    if ref:
        отпечаток["клонирование"] = 2
    прежний = st.load(work)
    if прежний and прежний.get("отпечаток") != отпечаток:
        import shutil
        print(т("прежняя работа не подходит ({голос}), начинаю заново",
                голос=прежний.get("отпечаток", {}).get("голос")), flush=True)
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work, exist_ok=True)
    elif прежний and not прежний.get("завершён"):
        сделано = прежний.get("фрагментов_готово", 0)
        print(f"ПРОДОЛЖАЮ прерванный прогон: этап «{прежний.get('этап')}»"
              + (f", фрагментов готово {сделано}" if сделано else ""), flush=True)
    st.save(work, отпечаток=отпечаток, завершён=False, этап="извлечение")

    model = args.model or (CUSTOM_VOICE_MODEL if preset else None)
    print(т("книга:    {имя}", имя=os.path.basename(book)))
    print(т("язык:     {язык}", язык=lang))
    if kokoro:
        print(т("голос:    {имя} ({движок}, быстрый синтез)", имя=kokoro[1], движок=kokoro[0]))
    elif apple:
        print(т("голос:    {имя} (системный, подсветка по словам)", имя=apple.split(".")[-1]))
    elif preset:
        print(т("голос:    {имя} (пресет)", имя=preset))
    else:
        print(т("голос:    {имя}", имя=os.path.basename(ref)))
    if abs(args.speed - 1.0) > 1e-3:
        print(т("темп:     {темп}x", темп=args.speed))
    print(т("папка:    {папка}", папка=dest))
    что = {"both": "аудиокнига и EPUB", "m4b": "аудиокнига"}.get(args.format, "EPUB с подсветкой")
    print(т("результат: {что}", что=т(что)) + "\n", flush=True)

    # narrate.py всегда исполняется интерпретатором своего движка: там
    # стоят и библиотека синтеза, и ebooklib для разбора книги. Служебный
    # интерпретатор приложения их не содержит и содержать не должен.
    sys.path.insert(0, os.path.join(HERE, "engines"))
    from registry import env_python, is_ready

    движок = kokoro[0] if kokoro else ("apple" if apple else "qwen")
    if not is_ready(движок):
        print("ЭТАП " + т("ставлю движок {движок}", движок=движок), flush=True)
        код = subprocess.call([sys.executable,
                               os.path.join(HERE, "engines", "install.py"),
                               движок])
        if код != 0 or not is_ready(движок):
            sys.exit(т("движок {движок} не установился", движок=движок))
    engine_py = env_python(движок)
    if subprocess.call([engine_py, "-c", "import imageio_ffmpeg"],
                       stderr=subprocess.DEVNULL) != 0:
        print("ЭТАП " + т("ставлю ffmpeg"), flush=True)
        subprocess.call([engine_py, "-m", "pip", "install", "-q",
                         "--disable-pip-version-check", "imageio-ffmpeg==0.6.0"])

    narrate = [engine_py, os.path.join(HERE, "narrate.py"),
               "--epub", book, "--out", work,
               "--language", spoken, "--lang-code", code,
               "--workers", str(args.workers),
               "--batch", str(args.batch)]
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
    print("ЭТАП " + т("сборка"), flush=True)

    title = os.path.splitext(os.path.basename(book))[0][:70]
    produced, commands = [], [" ".join(narrate)]

    if args.format in ("epub", "both"):
        print("ЭТАП " + т("сборка книги с подсветкой"), flush=True)
        # Озвучка добавляется в исходную книгу: вёрстка, картинки и стили
        # остаются на месте.
        mo = [engine_py, os.path.join(HERE, "mo.py"), "--out", work,
              "--source", book, "--epub", final, "--speed", str(args.speed)]
        run_stage(mo, "сборка EPUB")
        commands.append(" ".join(mo))
        produced.append(final)

    if args.format in ("m4b", "both"):
        print("ЭТАП " + т("сборка аудиокниги"), flush=True)
        asm = [engine_py, os.path.join(HERE, "assemble.py"), "--out", work,
               "--title", title, "--m4b"]
        run_stage(asm, "сборка аудиокниги")
        commands.append(" ".join(asm))
        built = os.path.join(work, "audiobook.m4b")
        if os.path.exists(built):
            os.replace(built, m4b)
            produced.append(m4b)

    manifest = os.path.join(work, "manifest.json")
    json.dump({"книга": book, "язык": lang, "формат": args.format,
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
        parts_dir = os.path.join(work, "parts")
        total = sum(длительность_wav(os.path.join(parts_dir, n))
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
    # Любая ошибка должна дойти до окна строкой СБОЙ, иначе прогон просто
    # исчезает и человек видит пустой экран без объяснения.
    try:
        main()
    except SystemExit as e:
        причина = e.code if isinstance(e.code, str) else ""
        if причина:
            print(f"СБОЙ {причина}", flush=True)
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"СБОЙ {type(e).__name__}: {str(e)[:160]}", flush=True)
        sys.exit(1)
