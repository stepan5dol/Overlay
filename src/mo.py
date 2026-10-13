"""Озвучка добавляется в исходный EPUB, а не строится новый.

Прежняя сборка выкидывала всё, кроме текста: вёрстку, картинки, стили.
Здесь исходная книга берётся как основа, а в её XHTML вставляются
<span id> вокруг озвученных фрагментов -- ровно там, где этот текст
лежит в разметке. Остальное не трогается вовсе, поэтому книга выглядит
как оригинал.

Сопоставление идёт по нормализованному тексту: фрагменты нарезались из
"плоского" текста, а в разметке те же слова разбиты тегами.
"""
import argparse, html, json, os, re, shutil, subprocess, sys, unicodedata, zipfile
import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools import ffmpeg as найти_ffmpeg, прочитать_wav
from narrate import ЗАМЕНЫ, ВЫБРОСИТЬ
from ui import т

SR = 24000
NS = {"opf": "http://www.idpf.org/2007/opf",
      "c": "urn:oasis:names:tc:opendocument:xmlns:container"}


def clock(s):
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:06.3f}"


НЕ_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def нормализовать(t):
    """Текст фрагмента без лишних пробелов -- для сопоставления.

    Разметки во фрагменте нет: он взят из get_text(). Вырезать «теги» из
    него нельзя -- так пропадало всё между «p < 0.05» и следующим «>».
    """
    return re.sub(r"\s+", " ", НЕ_XML.sub("", t)).strip()


def развернуть(t):
    """Раскрыть &#x27; и подобное: в разметке они, в тексте фрагмента -- нет."""
    return html.unescape(t)


# Нарезка выбрасывает то же самое (sup и sub -- номера сносок), иначе
# «Motion Bank,11 launched» в разметке не совпадёт с озвученным фрагментом.
СЛУЖЕБНЫЕ = ("title", "head") + ВЫБРОСИТЬ


def тело(xhtml):
    """Границы <body>: размечать что-либо вне его нельзя."""
    m = re.search(r"<body\b[^>]*>", xhtml)
    if not m:
        return 0, len(xhtml)
    конец = xhtml.rfind("</body>")
    return m.end(), (конец if конец > 0 else len(xhtml))


def текстовые_узлы(xhtml):
    """Куски текста вне тегов: (начало, конец, текст).

    Сопоставлять по сырой разметке нельзя -- совпадение может попасть в
    атрибут. Поэтому сначала выделяем текстовые узлы, а поиск ведём по
    склеенному из них тексту, помня, откуда каждый символ взялся.
    """
    начало, конец = тело(xhtml)
    узлы, поз, пропуск = [], начало, 0
    for m in re.finditer(r"<[^>]+>", xhtml):
        if m.end() <= начало:
            continue
        if m.start() >= конец:
            break
        имя = re.match(r"</?\s*([A-Za-z0-9]+)", m.group(0))
        имя = имя.group(1).lower() if имя else ""
        if m.start() > поз and not пропуск:
            узлы.append((поз, m.start(), xhtml[поз:m.start()]))
        if имя in СЛУЖЕБНЫЕ and not m.group(0).endswith("/>"):
            # <link/> и <meta/> закрыты сами: считать их открытыми --
            # потерять весь текст после них.
            пропуск += 0 if m.group(0).startswith("</") else 1
            if m.group(0).startswith("</"):
                пропуск = max(0, пропуск - 1)
        поз = m.end()
    if поз < конец and not пропуск:
        узлы.append((поз, конец, xhtml[поз:конец]))
    return узлы


def карта_текста(узлы):
    """Плоский текст документа и позиция каждого его символа в разметке.

    Ссылки вида &#x27; в разметке занимают шесть символов, а в тексте --
    один. Разворачиваем их, сохраняя привязку к исходным позициям, иначе
    фрагмент с апострофом не находится и остаётся без подсветки.
    """
    буквы, места = [], []
    for a, _b, t in узлы:
        k = 0
        while k < len(t):
            m = re.match(r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z]+);", t[k:])
            if m:
                # Ссылка занимает несколько символов разметки: началом
                # считаем её начало, а концом -- конец, чтобы граница span
                # не встала внутрь.
                развёрнутое = html.unescape(m.group(0))
                for j, ch in enumerate(развёрнутое):
                    буквы.append(ch)
                    места.append((a + k, a + k + m.end()))
                k += m.end()
            else:
                буквы.append(t[k])
                места.append((a + k, a + k + 1))
                k += 1
    return "".join(буквы), места


def разметить(xhtml, фрагменты, префикс):
    """Обернуть каждый фрагмент в <span id>, не трогая остальную разметку.

    Фрагмент может лежать в нескольких элементах сразу (заголовок и первое
    предложение, абзац с курсивом). Оборачивать его одним span нельзя --
    теги пересекутся и XML сломается. Поэтому фрагмент режется по границам
    текстовых узлов, и каждый кусок получает свой span с общим id-корнем;
    SMIL ссылается на первый.
    """
    узлы = текстовые_узлы(xhtml)
    плоский, места = карта_текста(узлы)

    # Текст разметки чистится так же, как нарезка чистила фрагменты
    # (narrate.clean_block). Каждый символ помнит первый и последний символ
    # плоского текста, из которых он получился.
    сжатый, начала, концы = [], [], []
    пробел = False
    for i, ch in enumerate(плоский):
        ch = ЗАМЕНЫ.get(ch, ch)
        if not ch:
            continue
        if ch.isspace():
            if not пробел and сжатый:
                сжатый.append(" "); начала.append(i); концы.append(i)
            пробел = True
            continue
        пробел = False
        if unicodedata.combining(ch) and сжатый:
            # Нарезка приводит текст к NFC: «e» и отдельное ударение там --
            # одна буква «é». Склеиваем так же, продлевая букву до знака.
            слитно = unicodedata.normalize("NFC", сжатый[-1] + ch)
            if len(слитно) == 1:
                сжатый[-1] = слитно; концы[-1] = i
                continue
        for c in unicodedata.normalize("NFC", ch):
            сжатый.append(c); начала.append(i); концы.append(i)
    сжатый = "".join(сжатый)

    границы = [(a, b) for a, b, _t in узлы]
    вставки, размечено, поз = [], [], 0

    for i, текст in enumerate(фрагменты):
        цель = нормализовать(текст)
        # К заголовкам при нарезке дописывается точка -- ради паузы в
        # синтезе. В разметке её нет, поэтому ищем без точки, а если в
        # разметке она есть, забираем её в span. Искать сначала с точкой
        # нельзя: для буквы «A» в указателе находилось «S.A.» через десять
        # страниц, и всё между ними выпадало.
        точка = цель.endswith(".")
        if точка:
            цель = цель[:-1]
        if not цель:
            continue
        k = сжатый.find(цель, поз)
        if k < 0:
            continue
        конец = k + len(цель)
        if точка and сжатый[конец:конец + 1] == ".":
            конец += 1
        a = места[начала[k]][0]
        b = места[концы[конец - 1]][1]
        куски = разрезать_по_узлам(a, b, границы)
        if not куски:
            continue
        for j, (ка, кб) in enumerate(куски):
            ident = f"{префикс}{i:04d}" if j == 0 else f"{префикс}{i:04d}_{j}"
            вставки.append((ка, кб, ident))
        размечено.append(i)
        поз = конец

    out = xhtml
    for a, b, ident in sorted(вставки, reverse=True):
        out = out[:a] + f'<span id="{ident}">' + out[a:b] + "</span>" + out[b:]
    return out, размечено


def разрезать_по_узлам(a, b, границы):
    """Части отрезка [a, b), каждая целиком внутри одного текстового узла."""
    куски = []
    for на, нб in границы:
        if нб <= a or на >= b:
            continue
        ка, кб = max(a, на), min(b, нб)
        if кб > ка and xhtml_непустой(ка, кб):
            куски.append((ка, кб))
    return куски


def xhtml_непустой(a, b):
    return b > a


def concat_chapter(chunks, parts, ci, fade_ms=8, words_by_id=None):
    n = int(SR * fade_ms / 1000)
    pieces, spans, t = [], [], 0.0
    for i, text in enumerate(chunks):
        p = os.path.join(parts, f"{ci:04d}_{i:04d}.wav")
        if not os.path.exists(p):
            continue
        y = прочитать_wav(p, SR).copy()
        if len(y) > 2 * n:
            y[:n] *= np.linspace(0, 1, n)
            y[-n:] *= np.linspace(1, 0, n)
        dur = len(y) / SR
        spans.append({"i": i, "begin": round(t, 3), "end": round(t + dur, 3)})
        pieces.append(y)
        пауза = 0.45 if text.rstrip().endswith((".", "!", "?", "”", ":")) else 0.25
        pieces.append(np.zeros(int(SR * пауза), dtype=np.float32))
        t += dur + пауза
    return (np.concatenate(pieces) if pieces else np.zeros(0, "float32")), spans, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="рабочая папка с фрагментами")
    ap.add_argument("--source", required=True, help="исходный EPUB")
    ap.add_argument("--epub", required=True, help="куда положить результат")
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args()

    chapters = json.load(open(os.path.join(args.out, "chapters.json")))
    parts = os.path.join(args.out, "parts")
    staging = os.path.join(args.out, "mo2")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)

    # исходная книга целиком -- основа результата
    with zipfile.ZipFile(args.source) as z:
        z.extractall(staging)
    вычистить(staging)

    opf_path = найти_opf(staging)
    base = os.path.dirname(opf_path)
    добавлено, общая = [], 0.0

    for ci, ch in enumerate(chapters):
        audio, spans, dur = concat_chapter(ch["chunks"], parts, ci)
        if not spans:
            continue
        # В chapters.json имя без пути, а в книге файл лежит глубже:
        # ищем по имени во всём распакованном дереве.
        имя_док = ch.get("name")
        путь_док = найти_документ(staging, имя_док)
        if not путь_док:
            print(f"  глава {ci}: исходный файл не найден ({имя_док}), пропускаю",
                  file=sys.stderr)
            continue

        xhtml = open(путь_док, encoding="utf-8").read()
        размеченный, размечено = разметить(xhtml, ch["chunks"], f"ov{ci}_")
        доля = len(размечено) / max(len(spans), 1)
        open(путь_док, "w", encoding="utf-8").write(размеченный)

        wav = os.path.join(staging, base and "", f"_ch{ci}.wav")
        wav = os.path.join(staging, f"_ch{ci}.wav")
        sf.write(wav, audio, SR)
        if abs(args.speed - 1.0) > 1e-3:
            быстрее = wav.replace(".wav", "_s.wav")
            subprocess.run([найти_ffmpeg(), "-y", "-v", "error", "-i", wav,
                            "-filter:a", f"atempo={args.speed:.4f}", быстрее],
                           check=True)
            os.replace(быстрее, wav)
            dur /= args.speed
            for s in spans:
                s["begin"] /= args.speed
                s["end"] /= args.speed

        audio_rel = f"audio/ov{ci}.mp4"
        audio_abs = os.path.join(base, audio_rel)
        os.makedirs(os.path.dirname(audio_abs), exist_ok=True)
        subprocess.run([найти_ffmpeg(), "-y", "-v", "error", "-i", wav,
                        "-c:a", "aac", "-b:a", "96k", audio_abs], check=True)
        os.remove(wav)

        smil_rel = f"smil/ov{ci}.smil"
        smil_abs = os.path.join(base, smil_rel)
        os.makedirs(os.path.dirname(smil_abs), exist_ok=True)
        отн_текст = os.path.relpath(путь_док, os.path.dirname(smil_abs))
        отн_звук = os.path.relpath(audio_abs, os.path.dirname(smil_abs))
        пары = "\n".join(
            f'<par id="p{k}"><text src="{отн_текст}#ov{ci}_{s["i"]:04d}"/>'
            f'<audio src="{отн_звук}" clipBegin="{clock(s["begin"])}"'
            f' clipEnd="{clock(s["end"])}"/></par>'
            for k, s in enumerate(spans) if s["i"] in размечено)
        open(smil_abs, "w", encoding="utf-8").write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<smil xmlns="http://www.w3.org/ns/SMIL" '
            'xmlns:epub="http://www.idpf.org/2007/ops" version="3.0"><body>\n'
            f'<seq id="s{ci}" epub:textref="{отн_текст}" epub:type="chapter">\n'
            f'{пары}\n</seq></body></smil>')

        добавлено.append({"ci": ci, "документ": имя_док, "smil": smil_rel,
                          "audio": audio_rel, "dur": dur})
        общая += dur
        print(f"  глава {ci}: {len(размечено)} из {len(spans)} фрагментов "
              f"размечено ({доля:.0%}), {dur/60:.1f} мин")

    вписать_в_opf(opf_path, добавлено, общая)
    проверить(staging)
    упаковать(staging, args.epub)
    shutil.rmtree(staging, ignore_errors=True)
    print(f"\n{args.epub}  ({общая/60:.1f} мин звука)")


def вычистить(root):
    for d, _, files in os.walk(root):
        for f in files:
            if not f.endswith((".xhtml", ".html", ".opf", ".ncx")):
                continue
            p = os.path.join(d, f)
            try:
                s = open(p, encoding="utf-8", newline="").read()
            except UnicodeDecodeError:
                continue
            чисто = НЕ_XML.sub("", s)
            if чисто != s:
                open(p, "w", encoding="utf-8", newline="").write(чисто)


def проверить(root):
    """Каждый изменённый файл должен остаться разбираемым XML.

    Читалка на сломанном XML говорит только «книга повреждена», поэтому
    ошибка должна всплывать здесь, до выдачи результата.
    """
    import xml.etree.ElementTree as ET
    плохие = []
    for d, _, files in os.walk(root):
        for f in files:
            if not f.endswith((".xhtml", ".opf", ".smil")):
                continue
            p = os.path.join(d, f)
            try:
                ET.parse(p)
            except ET.ParseError as e:
                плохие.append(f"{os.path.relpath(p, root)}: {e}")
    if плохие:
        print("  ПОВРЕЖДЕНО:", file=sys.stderr)
        for x in плохие[:5]:
            print("   ", x, file=sys.stderr)
        raise RuntimeError(т("книга собралась бы повреждённой: {файл}",
                             файл=плохие[0].split(":", 1)[0]))


def найти_документ(root, имя):
    """Файл главы в распакованной книге -- по имени, без учёта пути."""
    if not имя:
        return None
    цель = os.path.basename(имя)
    for d, _, files in os.walk(root):
        if цель in files:
            return os.path.join(d, цель)
    return None


def найти_opf(root):
    import xml.etree.ElementTree as ET
    c = ET.parse(os.path.join(root, "META-INF", "container.xml")).getroot()
    rel = c.find(".//c:rootfile", NS).get("full-path")
    return os.path.join(root, rel)


def вписать_в_opf(opf_path, добавлено, общая):
    """Прописать overlay к главам и объявить новые файлы в манифесте."""
    s = open(opf_path, encoding="utf-8").read()
    items, durs = [], []
    for a in добавлено:
        i = a["ci"]
        items.append(f'<item id="ovsmil{i}" href="{a["smil"]}" '
                     f'media-type="application/smil+xml"/>')
        items.append(f'<item id="ovaudio{i}" href="{a["audio"]}" '
                     f'media-type="audio/mp4"/>')
        durs.append(f'<meta property="media:duration" refines="#ovsmil{i}">'
                    f'{clock(a["dur"])}</meta>')
        # к существующему item главы дописываем media-overlay
        # Тег самозакрывающийся: атрибут идёт перед "/>", иначе XML ломается.
        шаблон = (r'<item\b[^>]*href="[^"]*'
                  + re.escape(os.path.basename(a["документ"])) + r'"[^>]*?>')

        def вписать(m):
            тег = m.group(0)
            if "media-overlay" in тег:
                return тег
            хвост = "/>" if тег.endswith("/>") else ">"
            return тег[: -len(хвост)] + f' media-overlay="ovsmil{i}"' + хвост

        s = re.sub(шаблон, вписать, s, count=1)
    s = s.replace("</manifest>", "\n".join(items) + "\n</manifest>")
    s = s.replace("</metadata>",
                  "\n".join(durs)
                  + f'\n<meta property="media:duration">{clock(общая)}</meta>'
                  + '\n<meta property="media:active-class">-epub-media-overlay-active</meta>'
                  + "\n</metadata>")
    open(opf_path, "w", encoding="utf-8").write(s)


def упаковать(root, dst):
    if os.path.exists(dst):
        os.remove(dst)
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        for d, _, files in os.walk(root):
            for f in files:
                p = os.path.join(d, f)
                rel = os.path.relpath(p, root)
                if rel == "mimetype":
                    continue
                z.write(p, rel, zipfile.ZIP_DEFLATED)


if __name__ == "__main__":
    main()
