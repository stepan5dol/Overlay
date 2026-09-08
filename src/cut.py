"""Одна глава книги -> отдельный маленький EPUB.

Нужен, чтобы подать конвейеру короткий вход и сравнить его с тем, что
вышло: целую книгу для проверки гонять незачем.
"""
import argparse, html, os, sys, uuid, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from narrate import extract

XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}" lang="{lang}">
<head><title>{title}</title></head>
<body><section>
{paras}
</section></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("epub")
    ap.add_argument("--only", type=int, required=True, help="номер главы")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="en")
    ap.add_argument("--title")
    args = ap.parse_args()

    chapters = extract(args.epub, 200)
    if not 0 <= args.only < len(chapters):
        sys.exit(f"главы {args.only} нет; всего {len(chapters)}")
    ch = chapters[args.only]
    title = args.title or ch["title"][:70]
    paras = "\n".join(f"<p>{html.escape(c)}</p>" for c in ch["chunks"])
    bid = "urn:uuid:" + str(uuid.uuid4())

    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid"
         xml:lang="{args.lang}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="bid">{bid}</dc:identifier>
<dc:title>{html.escape(title)}</dc:title>
<dc:language>{args.lang}</dc:language>
<meta property="dcterms:modified">2026-09-09T00:00:00Z</meta>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ch" href="chapter.xhtml" media-type="application/xhtml+xml"/>
</manifest>
<spine><itemref idref="ch"/></spine>
</package>"""
    nav = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<html xmlns="http://www.w3.org/1999/xhtml" '
           'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Оглавление</title>'
           '</head><body><nav epub:type="toc"><ol>'
           f'<li><a href="chapter.xhtml">{html.escape(title)}</a></li>'
           '</ol></nav></body></html>')

    with zipfile.ZipFile(args.out, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?>\n<container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/chapter.xhtml",
                   XHTML.format(title=html.escape(title), paras=paras, lang=args.lang))
    words = sum(len(c.split()) for c in ch["chunks"])
    print(f"{args.out}  ({len(ch['chunks'])} фрагментов, {words} слов)")


if __name__ == "__main__":
    main()
