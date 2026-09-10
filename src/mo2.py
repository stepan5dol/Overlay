"""Озвучка добавляется в исходный EPUB, а не строится новый.

Прежняя сборка выкидывала всё, кроме текста: вёрстку, картинки, стили.
Здесь исходная книга берётся как основа, а в её XHTML вставляются
<span id> вокруг озвученных фрагментов -- ровно там, где этот текст
лежит в разметке. Остальное не трогается вовсе, поэтому книга выглядит
как оригинал.

Сопоставление идёт по нормализованному тексту: фрагменты нарезались из
"плоского" текста, а в разметке те же слова разбиты тегами.
"""
import argparse, html, json, os, re, shutil, subprocess, sys, zipfile
import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools import ffmpeg as найти_ffmpeg

SR = 24000
NS = {"opf": "http://www.idpf.org/2007/opf",
      "c": "urn:oasis:names:tc:opendocument:xmlns:container"}


def clock(s):
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:06.3f}"


def нормализовать(t):
    """Текст без разметки и лишних пробелов -- для сопоставления."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t)).strip()


def текстовые_узлы(xhtml):
    """Куски текста вне тегов: (начало, конец, текст).

    Сопоставлять по сырой разметке нельзя -- совпадение может попасть в
    атрибут. Поэтому сначала выделяем текстовые узлы, а поиск ведём по
    склеенному из них тексту, помня, откуда каждый символ взялся.
    """
    узлы, поз = [], 0
    for m in re.finditer(r"<[^>]+>", xhtml):
        if m.start() > поз:
            узлы.append((поз, m.start(), xhtml[поз:m.start()]))
        поз = m.end()
    if поз < len(xhtml):
        узлы.append((поз, len(xhtml), xhtml[поз:]))
    return узлы


def карта_текста(узлы):
    """Плоский текст документа и позиция каждого его символа в разметке."""
    буквы, места = [], []
    for a, _b, t in узлы:
        for k, ch in enumerate(t):
            буквы.append(ch)
            места.append(a + k)
    return "".join(буквы), места


def разметить(xhtml, фрагменты, префикс):
    """Обернуть каждый фрагмент в <span id>, не трогая остальную разметку."""
    плоский, места = карта_текста(текстовые_узлы(xhtml))
    сжатый, индексы = [], []
    предыдущий_пробел = False
    for i, ch in enumerate(плоский):
        if ch.isspace():
            if not предыдущий_пробел and сжатый:
                сжатый.append(" "); индексы.append(i)
            предыдущий_пробел = True
        else:
            сжатый.append(ch); индексы.append(i)
            предыдущий_пробел = False
    сжатый = "".join(сжатый)

    найдено, поз = [], 0
    for i, текст in enumerate(фрагменты):
        цель = нормализовать(текст)
        if not цель:
            continue
        k = сжатый.find(цель, поз)
        if k < 0:                      # текст мог разойтись на кавычках
            k = сжатый.find(цель[:40], поз)
            if k < 0:
                continue
            конец_ц = k + len(цель)
        else:
            конец_ц = k + len(цель)
        конец_ц = min(конец_ц, len(индексы))
        a = места[индексы[k]]
        b = места[индексы[конец_ц - 1]] + 1
        найдено.append((a, b, f"{префикс}{i:04d}", i))
        поз = конец_ц

    out, размечено = xhtml, []
    for a, b, ident, i in reversed(найдено):
        out = out[:a] + f'<span id="{ident}">' + out[a:b] + "</span>" + out[b:]
        размечено.append(i)
    return out, sorted(размечено)


def concat_chapter(chunks, parts, ci, fade_ms=8, words_by_id=None):
    n = int(SR * fade_ms / 1000)
    pieces, spans, t = [], [], 0.0
    for i, text in enumerate(chunks):
        p = os.path.join(parts, f"{ci:04d}_{i:04d}.wav")
        if not os.path.exists(p):
            continue
        y, _ = sf.read(p, dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        y = y.copy()
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
    упаковать(staging, args.epub)
    shutil.rmtree(staging, ignore_errors=True)
    print(f"\n{args.epub}  ({общая/60:.1f} мин звука)")


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
        s = re.sub(r'(<item\b[^>]*href="[^"]*' + re.escape(os.path.basename(a["документ"]))
                   + r'"[^>]*)(/?>)',
                   lambda m: (m.group(1) + f' media-overlay="ovsmil{i}"' + m.group(2))
                   if "media-overlay" not in m.group(1) else m.group(0), s, count=1)
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
