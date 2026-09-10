"""Chunk texts + chunk audio -> EPUB 3 with Media Overlays.

Timings are exact by construction: every chunk is its own generation, so its
duration is known and no forced alignment is involved. Each chunk becomes one
<span id>, and the SMIL points at it with clipBegin/clipEnd into the chapter's
concatenated audio.
"""
import argparse, json, os, subprocess, sys, zipfile, html, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools import ffmpeg as найти_ffmpeg
import numpy as np, soundfile as sf

SR = 24000


def pause_after(text):
    return 0.45 if text.rstrip().endswith((".", "!", "?", "”", ":")) else 0.25


def word_spans(text, words, offset, base_id):
    """Разметка по словам: позиции приходят из системного синтеза.

    Между словами остаются пробелы и знаки препинания исходного текста --
    они попадают в разметку как есть, вне подсвечиваемых участков.
    """
    out, prev = [], 0
    for k, w in enumerate(sorted(words, key=lambda x: x["loc"])):
        lo, hi = w["loc"], w["loc"] + w["len"]
        if lo < prev:
            continue                       # перекрытие -- пропускаем слово
        out.append({"gap": text[prev:lo]} if lo > prev else None)
        out.append({"id": f"{base_id}w{k:03d}", "text": text[lo:hi],
                    "begin": round(offset + w["begin"], 3),
                    "end": round(offset + w["end"], 3)})
        prev = hi
    if prev < len(text):
        out.append({"gap": text[prev:]})
    return [x for x in out if x]


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
        w = (words_by_id or {}).get(f"{ci:04d}_{i:04d}")
        if w:
            spans.extend(word_spans(text, w, t, f"s{i:04d}"))
        else:
            spans.append({"id": f"s{i:04d}", "text": text,
                          "begin": round(t, 3), "end": round(t + dur, 3)})
        pieces.append(y)
        gap = pause_after(text)
        pieces.append(np.zeros(int(SR * gap), dtype=np.float32))
        t += dur + gap
    return (np.concatenate(pieces) if pieces else np.zeros(0, "float32")), spans, t


def clock(s):
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:06.3f}"


XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="{lang}" lang="{lang}">
<head><title>{title}</title>
<style>
 body {{ font: 1.1rem/1.7 Georgia, serif; margin: 1.4rem; max-width: 34rem; }}
 span.-epub-media-overlay-active {{ background: #ffe9a8; }}
</style></head>
<body><section epub:type="chapter"><h1>{title}</h1>
{paras}
</section></body></html>
"""

SMIL = """<?xml version="1.0" encoding="utf-8"?>
<smil xmlns="http://www.w3.org/ns/SMIL" xmlns:epub="http://www.idpf.org/2007/ops"
      version="3.0">
<body>
<seq id="seq{ci}" epub:textref="../text/ch{ci}.xhtml" epub:type="chapter">
{pars}
</seq>
</body></smil>
"""


def atempo_chain(speed):
    """ffmpeg atempo принимает 0.5..2.0 за раз, большее набирается цепочкой."""
    parts, s = [], speed
    while s > 2.0:
        parts.append("atempo=2.0"); s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5"); s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def retime(src, dst, speed):
    """Меняет темп, не трогая высоту голоса."""
    subprocess.run([найти_ffmpeg(), "-y", "-v", "error", "-i", src,
                    "-filter:a", atempo_chain(speed), dst], check=True)


def build(out_dir, epub_path, title, lang, speed=1.0):
    chapters = json.load(open(os.path.join(out_dir, "chapters.json")))
    parts = os.path.join(out_dir, "parts")
    wpath = os.path.join(out_dir, "words.json")
    words_by_id = json.load(open(wpath)) if os.path.exists(wpath) else None
    staging = os.path.join(out_dir, "mo"); os.makedirs(staging, exist_ok=True)

    items, navs, total, chdur = [], [], 0.0, {}
    for ci, ch in enumerate(chapters):
        audio, spans, dur = concat_chapter(ch["chunks"], parts, ci, words_by_id=words_by_id)
        if not spans:
            continue
        total += dur
        ap = os.path.join(staging, f"ch{ci}.wav")
        sf.write(ap, audio, SR)
        if abs(speed - 1.0) > 1e-3:
            fast = ap.replace(".wav", "_speed.wav")
            retime(ap, fast, speed)
            os.replace(fast, ap)
            dur /= speed                       # метки сжимаются ровно во столько же
            for s_ in spans:
                if "begin" in s_:
                    s_["begin"] /= speed
                    s_["end"] /= speed
        mp3 = os.path.join(staging, f"ch{ci}.mp4")
        subprocess.run([найти_ffmpeg(), "-y", "-v", "error", "-i", ap,
                        "-c:a", "aac", "-b:a", "96k", mp3], check=True)
        os.remove(ap)

        if words_by_id:
            body = "".join(html.escape(x["gap"]) if "gap" in x else
                           f'<span id="{x["id"]}">{html.escape(x["text"])}</span>'
                           for x in spans)
            paras = f"<p>{body}</p>"
        else:
            paras = "\n".join(
                f'<p><span id="{s["id"]}">{html.escape(s["text"])}</span></p>'
                for s in spans)
        open(os.path.join(staging, f"ch{ci}.xhtml"), "w").write(
            XHTML.format(title=html.escape(ch["title"][:70]), paras=paras, lang=lang))

        timed = [x for x in spans if "begin" in x]
        pars = "\n".join(
            f'<par id="p{i}"><text src="../text/ch{ci}.xhtml#{s["id"]}"/>'
            f'<audio src="../audio/ch{ci}.mp4" clipBegin="{clock(s["begin"])}"'
            f' clipEnd="{clock(s["end"])}"/></par>'
            for i, s in enumerate(timed))
        open(os.path.join(staging, f"ch{ci}.smil"), "w").write(
            SMIL.format(ci=ci, pars=pars))

        items.append(ci)
        chdur[ci] = dur
        navs.append((ci, ch["title"][:70]))
        print(f"  глава {ci}: {len(timed)} "
              f"{'слов' if words_by_id else 'фрагментов'}, {dur/60:.1f} мин")

    bid = "urn:uuid:" + str(uuid.uuid4())
    manifest = "\n".join(
        f'<item id="ch{ci}" href="text/ch{ci}.xhtml" media-type="application/xhtml+xml"'
        f' media-overlay="mo{ci}"/>\n'
        f'<item id="mo{ci}" href="smil/ch{ci}.smil" media-type="application/smil+xml"/>\n'
        f'<item id="au{ci}" href="audio/ch{ci}.mp4" media-type="audio/mp4"/>'
        for ci in items)
    spine_x = "\n".join(f'<itemref idref="ch{ci}"/>' for ci in items)
    durs = "\n".join(
        f'<meta property="media:duration" refines="#mo{ci}">{clock(chdur[ci])}</meta>'
        for ci in items)
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid"
         xml:lang="{lang}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="bid">{bid}</dc:identifier>
<dc:title>{html.escape(title)}</dc:title>
<dc:language>{lang}</dc:language>
<meta property="dcterms:modified">2026-09-07T00:00:00Z</meta>
{durs}
<meta property="media:duration">{clock(total)}</meta>
<meta property="media:active-class">-epub-media-overlay-active</meta>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
{manifest}
</manifest>
<spine>{spine_x}</spine>
</package>"""
    nav = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<html xmlns="http://www.w3.org/1999/xhtml" '
           'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Оглавление</title>'
           '</head><body><nav epub:type="toc"><ol>'
           + "".join(f'<li><a href="text/ch{ci}.xhtml">{html.escape(t)}</a></li>'
                     for ci, t in navs)
           + "</ol></nav></body></html>")

    with zipfile.ZipFile(epub_path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?>\n<container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        for ci in items:
            z.write(os.path.join(staging, f"ch{ci}.xhtml"), f"OEBPS/text/ch{ci}.xhtml")
            z.write(os.path.join(staging, f"ch{ci}.smil"), f"OEBPS/smil/ch{ci}.smil")
            z.write(os.path.join(staging, f"ch{ci}.mp4"), f"OEBPS/audio/ch{ci}.mp4")
    print(f"\n{epub_path}  ({total/60:.1f} мин звука)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--epub", required=True)
    ap.add_argument("--title", default="Книга")
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="темп речи; модель его не умеет, применяется после синтеза")
    a = ap.parse_args()
    build(a.out, a.epub, a.title, a.lang, a.speed)
