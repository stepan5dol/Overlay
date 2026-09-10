"""PDF -> EPUB с сохранением структуры и картинок.

Дальше эта книга идёт по обычному пути: озвучка и подсветка вставляются в
неё так же, как в любой другой EPUB.

Разбирает docling: он размечает страницу моделью и отделяет тело от
колонтитулов, а картинки отдаёт вместе с подписями. Распознавание текста
на изображениях отключено -- в книге есть текстовый слой, а стоит оно
десятикратного замедления.
"""
import argparse, base64, html, io, json, os, re, sys, uuid, zipfile

СТИЛЬ = """body { font: 1.05rem/1.65 Georgia, serif; margin: 1.2rem; }
h1, h2, h3 { line-height: 1.25; }
figure { margin: 1.4rem 0; text-align: center; }
figure img { max-width: 100%; }
figcaption { font-size: .85rem; color: #555; margin-top: .4rem; }
span.-epub-media-overlay-active { background: #ffe9a8; }"""


def разобрать(pdf, ocr=False):
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.base_models import InputFormat
    o = PdfPipelineOptions()
    o.generate_picture_images = True
    o.do_ocr = ocr
    conv = DocumentConverter(format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=o)})
    return conv.convert(pdf).document


def собрать_html(doc, картинки):
    """Документ docling -> XHTML по главам.

    Главы режутся по заголовкам первого уровня; если их нет -- вся книга
    одной главой, потом её всё равно поделит нарезка на фрагменты.
    """
    from docling_core.types.doc import DocItemLabel
    главы, текущая = [], {"заголовок": None, "куски": []}

    for элемент, _ in doc.iterate_items():
        м = getattr(элемент, "label", None)
        текст = (getattr(элемент, "text", "") or "").strip()

        if м == DocItemLabel.PICTURE:
            ident = f"img{len(картинки):04d}"
            картинка = getattr(элемент, "image", None)
            if картинка is not None and getattr(картинка, "pil_image", None):
                буфер = io.BytesIO()
                картинка.pil_image.save(буфер, format="PNG")
                картинки[ident] = буфер.getvalue()
                # Подпись docling не всегда привязывает к картинке, поэтому
                # берём следующий элемент-подпись, если он идёт сразу за ней.
                подпись = (элемент.caption_text(doc) or "").strip() \
                    if hasattr(элемент, "caption_text") else ""
                текущая["куски"].append(
                    ["figure", ident, подпись])
            continue

        if м == DocItemLabel.TABLE:
            # Таблица читается вслух плохо, но терять её нельзя: в книге
            # она часть содержания.
            try:
                разметка = элемент.export_to_html(doc)
            except Exception:
                разметка = ""
            if разметка:
                текущая["куски"].append(разметка)
            continue

        if not текст:
            continue
        if м in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER):
            continue                      # колонтитулы не читаются вслух
        if м == DocItemLabel.SECTION_HEADER or м == DocItemLabel.TITLE:
            if текущая["куски"]:
                главы.append(текущая)
            текущая = {"заголовок": текст, "куски": [
                f"<h1>{html.escape(текст)}</h1>"]}
            continue
        if м == DocItemLabel.CAPTION:
            # Подпись привязываем к картинке только если она идёт сразу за
            # ней. Иначе это подпись к таблице или заголовок раздела -- в
            # проверенном файле именно так и оказалось.
            последний = текущая["куски"][-1] if текущая["куски"] else None
            рядом = (isinstance(последний, list) and последний[0] == "figure"
                     and not последний[2])
            к_таблице = re.match(r"(?i)^tab(le|\.)\b|^таблиц", текст)
            if рядом and not к_таблице:
                последний[2] = текст
            else:
                текущая["куски"].append(
                    f'<p class="caption">{html.escape(текст)}</p>')
            continue
        if м == DocItemLabel.LIST_ITEM:
            текущая["куски"].append(f"<li>{html.escape(текст)}</li>")
            continue
        текущая["куски"].append(f"<p>{html.escape(текст)}</p>")

    if текущая["куски"]:
        главы.append(текущая)

    # заготовки картинок превращаем в разметку, когда подписи уже собраны
    for гл in главы:
        гл["куски"] = [
            (f'<figure><img src="../images/{к[1]}.png" alt=""/>'
             + (f"<figcaption>{html.escape(к[2])}</figcaption>" if к[2] else "")
             + "</figure>") if isinstance(к, list) else к
            for к in гл["куски"]]
    return главы


ШАБЛОН = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="{lang}" lang="{lang}">
<head><title>{title}</title>
<link href="../style.css" rel="stylesheet" type="text/css"/></head>
<body><section epub:type="chapter">
{body}
</section></body></html>
"""


def записать(главы, картинки, dst, название, lang):
    bid = "urn:uuid:" + str(uuid.uuid4())
    манифест, spine, nav = [], [], []
    файлы = {}

    for i, гл in enumerate(главы):
        имя = f"text/ch{i:04d}.xhtml"
        заголовок = гл["заголовок"] or f"Часть {i + 1}"
        файлы[имя] = ШАБЛОН.format(title=html.escape(заголовок[:70]),
                                   body="\n".join(гл["куски"]), lang=lang)
        манифест.append(f'<item id="ch{i}" href="{имя}" '
                        f'media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="ch{i}"/>')
        nav.append(f'<li><a href="{имя}">{html.escape(заголовок[:70])}</a></li>')

    for ident, данные in картинки.items():
        манифест.append(f'<item id="{ident}" href="images/{ident}.png" '
                        f'media-type="image/png"/>')

    манифест.append('<item id="css" href="style.css" media-type="text/css"/>')
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid"
         xml:lang="{lang}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="bid">{bid}</dc:identifier>
<dc:title>{html.escape(название)}</dc:title>
<dc:language>{lang}</dc:language>
<meta property="dcterms:modified">2026-09-10T00:00:00Z</meta>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
{chr(10).join(манифест)}
</manifest>
<spine>{chr(10).join(spine)}</spine>
</package>"""

    навигация = ('<?xml version="1.0" encoding="utf-8"?>\n'
                 '<html xmlns="http://www.w3.org/1999/xhtml" '
                 'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
                 '<title>Оглавление</title></head><body>'
                 '<nav epub:type="toc"><ol>' + "".join(nav) +
                 "</ol></nav></body></html>")

    if os.path.exists(dst):
        os.remove(dst)
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?>\n<container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", навигация)
        z.writestr("OEBPS/style.css", СТИЛЬ)
        for имя, текст in файлы.items():
            z.writestr("OEBPS/" + имя, текст)
        for ident, данные in картинки.items():
            z.writestr(f"OEBPS/images/{ident}.png", данные)


def проверить(epub):
    """Каждая ссылка внутри книги должна вести в существующий файл.

    Битая ссылка на картинку выглядит в читалке как пустой квадратик, и
    узнать об этом от читателя -- поздно.
    """
    import posixpath
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(epub)
    беды = []
    for n in z.namelist():
        if n.endswith((".xhtml", ".opf")):
            try:
                ET.fromstring(z.read(n))
            except ET.ParseError as e:
                беды.append(f"{n}: {e}")
        if not n.endswith(".xhtml"):
            continue
        h = z.read(n).decode("utf-8", "ignore")
        for ссылка in re.findall(r'(?:src|href)="([^"]+)"', h):
            if ссылка.startswith(("http", "#", "mailto:")):
                continue
            цель = posixpath.normpath(
                posixpath.join(posixpath.dirname(n), ссылка.split("#")[0]))
            if цель not in z.namelist():
                беды.append(f"{n}: ссылка в никуда — {ссылка}")
    if беды:
        for b in беды[:5]:
            print("  ПОВРЕЖДЕНО:", b, file=sys.stderr)
        raise RuntimeError(f"книга собралась бы битой ({len(беды)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="en")
    ap.add_argument("--title")
    ap.add_argument("--ocr", action="store_true",
                    help="распознавать текст на картинках (в десять раз дольше)")
    args = ap.parse_args()

    print("ЭТАП разбор PDF", flush=True)
    doc = разобрать(args.pdf, args.ocr)
    картинки = {}
    главы = собрать_html(doc, картинки)
    название = args.title or os.path.splitext(os.path.basename(args.pdf))[0]
    записать(главы, картинки, args.out, название, args.lang)
    проверить(args.out)
    слов = sum(len(re.sub(r"<[^>]+>", " ", "".join(г["куски"])).split())
               for г in главы)
    print(f"{args.out}  (глав {len(главы)}, картинок {len(картинки)}, "
          f"слов {слов})")


if __name__ == "__main__":
    main()
