"""Сравнение разборщиков PDF на одном файле.

Меряем не «красоту разметки», а то, что важно для озвучки: сохранился ли
порядок чтения, вычищены ли колонтитулы и ссылки, не слиплись ли слова на
переносах, найдены ли картинки.
"""
import argparse, json, os, re, sys, time

КОЛОНТИТУЛ = re.compile(r"(?m)^\s*\d{1,4}\s{2,}[A-ZА-Я][a-zа-я]+(?:\s+[A-ZА-Я][a-zа-я]+)?\s*$")
ССЫЛКА = re.compile(r"\((?:[^()]{0,80}?\b(?:1[5-9]|20)\d{2}[a-z]?\b[^()]{0,40})\)")
ПЕРЕНОС = re.compile(r"[a-zа-я]-\s*\n\s*[a-zа-я]")
СЛИПШИЕСЯ = re.compile(r"[a-zа-я]{2,}[A-ZА-Я][a-zа-я]{2,}")


def оценить(текст):
    слова = текст.split()
    return {
        "слов": len(слова),
        "колонтитулов": len(КОЛОНТИТУЛ.findall(текст)),
        "ссылок": len(ССЫЛКА.findall(текст)),
        "неслитых_переносов": len(ПЕРЕНОС.findall(текст)),
        "слипшихся_слов": len(СЛИПШИЕСЯ.findall(текст)),
        "картинок": len(re.findall(r"!\[", текст)),
    }


def запустить(имя, pdf):
    """Разбор одним из способов. Каждый живёт в своём окружении."""
    if имя == "pymupdf4llm":
        import pymupdf4llm, tempfile, glob
        d = tempfile.mkdtemp()
        md = pymupdf4llm.to_markdown(pdf, write_images=True, image_path=d)
        картинки = {os.path.basename(f): f
                    for f in glob.glob(os.path.join(d, "*"))}
        return md, картинки
    if имя == "docling":
        from docling.document_converter import DocumentConverter
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        o = PdfPipelineOptions()
        o.generate_picture_images = True
        conv = DocumentConverter(format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=o)})
        d = conv.convert(pdf).document
        картинки = {f"p{i}": p for i, p in enumerate(d.pictures or [])}
        return d.export_to_markdown(), картинки
    if имя == "marker":
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered
        c = PdfConverter(artifact_dict=create_model_dict())
        текст, _, картинки = text_from_rendered(c(pdf))
        return текст, картинки
    if имя == "наш":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out = f.name
        subprocess.run([sys.executable, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "extract.py"),
            "--pdf", pdf, "--first", "1", "--last", "999", "--out", out],
            capture_output=True)
        d = json.load(open(out))
        os.unlink(out)
        return "\n".join(d["sentences"])
    sys.exit(f"неизвестный разборщик: {имя}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--parser", required=True)
    ap.add_argument("--save", help="куда положить получившийся текст")
    args = ap.parse_args()

    t0 = time.time()
    результат = запустить(args.parser, args.pdf)
    текст, картинки = результат if isinstance(результат, tuple) else (результат, {})
    сек = time.time() - t0
    итог = {"разборщик": args.parser, "секунд": round(сек, 1),
            "картинок_извлечено": len(картинки), **оценить(текст)}
    if args.save:
        open(args.save, "w", encoding="utf-8").write(текст)
    print(json.dumps(итог, ensure_ascii=False))


if __name__ == "__main__":
    main()
