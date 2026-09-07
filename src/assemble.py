"""Chunk WAVs -> chapter WAVs -> one M4B with chapter markers.

Chunks are joined with a short pause whose length follows the punctuation
that ended the chunk, and the joint is cross-faded over a few milliseconds
so the seam does not click.
"""
import argparse, json, os, subprocess
import numpy as np, soundfile as sf

SR = 24000


def pause_after(text, sentence=0.45, para=0.75, clause=0.25):
    t = text.rstrip()
    if t.endswith((".", "!", "?", "”", ":")):
        return sentence
    return clause


def fade_join(pieces, fade_ms=8):
    n = int(SR * fade_ms / 1000)
    out = []
    for i, y in enumerate(pieces):
        y = y.copy()
        if len(y) > 2 * n:
            y[:n] *= np.linspace(0, 1, n)
            y[-n:] *= np.linspace(1, 0, n)
        out.append(y)
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def build_chapter(chunks, parts, ci):
    pieces = []
    for i, text in enumerate(chunks):
        p = os.path.join(parts, f"{ci:04d}_{i:04d}.wav")
        if not os.path.exists(p):
            continue
        y, _ = sf.read(p, dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        pieces.append(y)
        pieces.append(np.zeros(int(SR * pause_after(text)), dtype=np.float32))
    return fade_join(pieces)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="Аудиокнига")
    ap.add_argument("--m4b", action="store_true")
    args = ap.parse_args()

    chapters = json.load(open(os.path.join(args.out, "chapters.json")))
    parts = os.path.join(args.out, "parts")
    chdir = os.path.join(args.out, "chapters"); os.makedirs(chdir, exist_ok=True)

    ready = []
    for ci, ch in enumerate(chapters):
        y = build_chapter(ch["chunks"], parts, ci)
        if len(y) < SR:
            continue
        p = os.path.join(chdir, f"{ci:04d}.wav")
        sf.write(p, y, SR)
        ready.append({"title": ch["title"][:60], "path": p, "dur": len(y) / SR})
        print(f"  {ci:04d}  {len(y)/60/SR:6.2f} мин  {ch['title'][:50]}")

    if not args.m4b or not ready:
        return
    lst = os.path.join(args.out, "list.txt")
    meta = os.path.join(args.out, "meta.txt")
    with open(lst, "w") as f:
        for r in ready:
            f.write(f"file '{os.path.abspath(r['path'])}'\n")
    lines = [";FFMETADATA1", f"title={args.title}"]
    t = 0
    for r in ready:
        d = int(r["dur"] * 1000)
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={t}", f"END={t+d}",
                  "title=" + r["title"].replace("=", " ").replace(";", " ")]
        t += d
    open(meta, "w").write("\n".join(lines))
    dst = os.path.join(args.out, "audiobook.m4b")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-i", meta, "-map_metadata", "1",
                    "-c:a", "aac", "-b:a", "128k", "-vn", dst], check=True)
    print(f"\n{dst}  ({t/3600000:.2f} ч)")


if __name__ == "__main__":
    main()
