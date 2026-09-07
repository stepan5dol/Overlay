"""PDF chapter -> clean sentences, ready for TTS.

Every cleanup step is separately switchable so its effect can be measured
(see --keep). Blocks come from PyMuPDF with coordinates, which is what makes
running-head removal reliable: they are identified by position on the page,
not by guessing at the text.
"""
import argparse, json, re, statistics, sys
import fitz

ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)
# author-date citations: (Posen 1988), (Karber and Combs 1998), (NATO 1984, 12-14)
CITATION = re.compile(r"\s*\((?:[^()]{0,80}?\b(?:1[5-9]|20)\d{2}[a-z]?\b[^()]{0,40})\)")
# bare year-only parentheticals left behind after an inline author name
BRACKET_ELLIPSIS = re.compile(r"\[\s*\.\s*\.\s*\.\s*\]")
EDITORIAL = re.compile(r"\[([a-z]{1,3})\]")          # ha[d] -> had
SENT_END = re.compile(r"(?<=[.!?’\"])\s+(?=[‘\"(]?[A-Z0-9])")
ABBREV = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|St|Jr|Sr|vs|etc|cf|Fig|No|Vol|ed|eds|pp|al)\.$", re.I)


def page_blocks(page, header_band, footer_band):
    """Text blocks with running heads and footers dropped by y-position."""
    h = page.rect.height
    out = []
    for x0, y0, x1, y1, text, _no, btype in page.get_text("blocks"):
        if btype != 0:
            continue                                  # image block
        if y0 < h * header_band or y1 > h * (1 - footer_band):
            continue                                  # running head / folio
        out.append(text)
    return out


def join_lines(block):
    """Rejoin visually wrapped lines, healing hyphenation across line breaks."""
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    buf = ""
    for ln in lines:
        if not buf:
            buf = ln
        elif buf.endswith("-"):
            # word split across lines: drop the hyphen only for lowercase
            # continuations, so "East-\nWest" and "self-\nevident" survive.
            buf = buf[:-1] + ln if ln[:1].islower() else buf + ln
        else:
            buf += " " + ln
    return buf


def clean(text, keep):
    text = text.translate(ZERO_WIDTH)
    text = text.replace(" ", " ").replace(" ", " ")
    if "citations" not in keep:
        text = CITATION.sub("", text)
    if "editorial" not in keep:
        text = BRACKET_ELLIPSIS.sub("…", text)
        text = EDITORIAL.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(para):
    parts, buf = [], ""
    for piece in SENT_END.split(para):
        buf = (buf + " " + piece).strip() if buf else piece
        if not ABBREV.search(buf):
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--first", type=int, required=True, help="1-based, inclusive")
    ap.add_argument("--last", type=int, required=True, help="1-based, inclusive")
    ap.add_argument("--title", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--header-band", type=float, default=0.075)
    ap.add_argument("--footer-band", type=float, default=0.055)
    ap.add_argument("--min-words", type=int, default=3,
                    help="drop shorter blocks (stray folios, figure labels)")
    ap.add_argument("--keep", default="", help="comma-separated: citations,editorial")
    args = ap.parse_args()

    keep = {k for k in args.keep.split(",") if k}
    doc = fitz.open(args.pdf)
    paragraphs = []
    for pno in range(args.first - 1, args.last):
        for block in page_blocks(doc[pno], args.header_band, args.footer_band):
            para = clean(join_lines(block), keep)
            if len(para.split()) >= args.min_words:
                paragraphs.append(para)

    sentences = [s for p in paragraphs for s in split_sentences(p)]
    lens = [len(s.split()) for s in sentences] or [0]
    meta = {
        "source": args.pdf, "title": args.title,
        "pages": [args.first, args.last], "kept": sorted(keep),
        "paragraphs": len(paragraphs), "sentences": len(sentences),
        "words": sum(lens),
        "sentence_words": {"median": statistics.median(lens), "max": max(lens)},
    }
    with open(args.out, "w") as f:
        json.dump({"meta": meta, "sentences": sentences}, f,
                  ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False, indent=1), file=sys.stderr)


if __name__ == "__main__":
    main()
