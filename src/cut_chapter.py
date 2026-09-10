"""Одна глава книги -> отдельный EPUB со своей вёрсткой и картинками.

Нужен, чтобы проверять конвейер на коротком входе. Книга берётся как есть, а из неё удаляются лишние главы: остаётся
целевая со своей разметкой, картинками и стилями.
"""
import argparse, os, re, shutil, sys, zipfile
import xml.etree.ElementTree as ET

NS = {"opf": "http://www.idpf.org/2007/opf",
      "c": "urn:oasis:names:tc:opendocument:xmlns:container"}


def найти_opf(root):
    c = ET.parse(os.path.join(root, "META-INF", "container.xml")).getroot()
    return os.path.join(root, c.find(".//c:rootfile", NS).get("full-path"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("epub")
    ap.add_argument("--from", dest="начало", type=int, default=0,
                    help="с какой главы (номер как в --only конвейера)")
    ap.add_argument("--count", type=int, default=1, help="сколько глав подряд")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    work = args.out + ".tmp"
    shutil.rmtree(work, ignore_errors=True)
    with zipfile.ZipFile(args.epub) as z:
        z.extractall(work)

    opf_path = найти_opf(work)
    base = os.path.dirname(opf_path)
    ET.register_namespace("", NS["opf"])
    tree = ET.parse(opf_path)
    root = tree.getroot()
    manifest = root.find("opf:manifest", NS)
    spine = root.find("opf:spine", NS)

    # Нумерация как в narrate.py: он пропускает документы без текста.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import warnings; warnings.filterwarnings("ignore")
    from narrate import extract
    главы = extract(args.epub, 200)
    нужные = главы[args.начало:args.начало + args.count]
    if not нужные:
        sys.exit(f"глав с {args.начало} нет; всего {len(главы)}")
    файлы = {os.path.basename(c["name"]) for c in нужные}

    держим = set()
    for it in manifest.findall("opf:item", NS):
        href = os.path.basename(it.get("href"))
        props = it.get("properties", "")
        # документы -- только нужные; всё прочее (картинки, стили,
        # оглавление) остаётся: оно и делает книгу похожей на исходную
        if it.get("media-type") != "application/xhtml+xml":
            держим.add(it.get("id"))
        elif href in файлы or "nav" in props:
            держим.add(it.get("id"))
    оставить_ids = {it.get("id") for it in manifest.findall("opf:item", NS)
                    if os.path.basename(it.get("href")) in файлы}

    удалено = []
    for it in list(manifest.findall("opf:item", NS)):
        if it.get("id") in держим:
            continue
        p = os.path.join(base, it.get("href"))
        if os.path.exists(p):
            os.remove(p)
        удалено.append(it.get("href"))
        manifest.remove(it)
    for ir in list(spine.findall("opf:itemref", NS)):
        if ir.get("idref") not in оставить_ids:
            spine.remove(ir)

    tree.write(opf_path, encoding="utf-8", xml_declaration=True)

    if os.path.exists(args.out):
        os.remove(args.out)
    with zipfile.ZipFile(args.out, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        for d, _, files in os.walk(work):
            for f in files:
                p = os.path.join(d, f)
                rel = os.path.relpath(p, work)
                if rel != "mimetype":
                    z.write(p, rel, zipfile.ZIP_DEFLATED)
    shutil.rmtree(work, ignore_errors=True)

    with zipfile.ZipFile(args.out) as z:
        карт = sum(1 for n in z.namelist()
                   if n.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".svg")))
    print(f"{args.out}  ({os.path.getsize(args.out)/1048576:.1f} МБ, "
          f"глав {len(нужные)}, картинок {карт})")
    for i, c in enumerate(нужные, start=args.начало):
        print(f"   {i}: {c['title'][:60]}")


if __name__ == "__main__":
    main()
