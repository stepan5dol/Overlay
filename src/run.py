"""One command per book: описание в TOML -> озвучка -> EPUB с media overlay.

Каждый прогон пишет рядом с результатом manifest.json: настройки, модель,
контрольная сумма референса, версии библиотек, коммит репозитория. По нему
прогон восстанавливается без обращения к истории команд.
"""
import argparse, hashlib, json, os, subprocess, sys, tomllib
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def sha256(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def versions(python):
    code = ("import json,importlib.metadata as m;"
            "print(json.dumps({p:(m.version(p) if _try(p) else None) "
            "for p in ['mlx','mlx-audio','transformers','soundfile','ebooklib']}))")
    probe = ("import importlib.metadata as m\n"
             "def _try(p):\n"
             "    try: m.version(p); return True\n"
             "    except Exception: return False\n") + code
    try:
        out = subprocess.run([python, "-c", probe], capture_output=True,
                             text=True, timeout=60).stdout.strip()
        return json.loads(out)
    except Exception:
        return {}


def git_commit():
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip() or None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book", help="файл описания книги, books/*.toml")
    ap.add_argument("--skip-synth", action="store_true")
    ap.add_argument("--skip-epub", action="store_true")
    args = ap.parse_args()

    with open(args.book, "rb") as f:
        cfg = tomllib.load(f)
    # пути в описании могут быть относительными -- считаем их от корня репозитория
    for k in ("epub", "ref_audio", "ref_text"):
        if cfg.get(k) and not os.path.isabs(cfg[k]):
            cfg[k] = os.path.join(ROOT, cfg[k])

    py = cfg.get("python", sys.executable)
    out = os.path.join(ROOT, cfg["out"])
    os.makedirs(out, exist_ok=True)

    narrate = [py, os.path.join(HERE, "narrate.py"),
               "--epub", cfg["epub"], "--out", out,
               "--language", cfg.get("language", "Russian"),
               "--lang-code", cfg.get("lang_code", "ru"),
               "--target", str(cfg.get("target", 200)),
               "--workers", str(cfg.get("workers", 3)),
               "--temperature", str(cfg.get("temperature", 0.8)),
               "--top-p", str(cfg.get("top_p", 0.8))]
    if cfg.get("model"):
        narrate += ["--model", cfg["model"]]
    if cfg.get("voice"):
        narrate += ["--voice", cfg["voice"]]
    else:
        narrate += ["--ref-audio", cfg["ref_audio"], "--ref-text", cfg["ref_text"]]
    if cfg.get("only") is not None:
        narrate += ["--only", str(cfg["only"])]
    if cfg.get("limit_chunks"):
        narrate += ["--limit-chunks", str(cfg["limit_chunks"])]

    if not args.skip_synth:
        print("$ " + " ".join(narrate), flush=True)
        if subprocess.run(narrate).returncode != 0:
            sys.exit("синтез завершился с ошибкой")

    epub_out = os.path.join(ROOT, cfg["epub_out"])
    mo = [py, os.path.join(HERE, "mo.py"), "--out", out, "--epub", epub_out,
          "--title", cfg.get("title", "Книга"), "--lang", cfg.get("lang_code", "ru")]
    if not args.skip_epub:
        print("$ " + " ".join(mo), flush=True)
        if subprocess.run(mo).returncode != 0:
            sys.exit("сборка EPUB завершилась с ошибкой")

    manifest = {
        "создан": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "описание_книги": os.path.relpath(args.book, ROOT),
        "настройки": cfg,
        "коммит": git_commit(),
        "источник_sha256": sha256(cfg["epub"]),
        "версии": versions(py),
        "команды": [" ".join(narrate), " ".join(mo)],
    }
    if cfg.get("ref_audio"):
        manifest["референс_sha256"] = sha256(cfg["ref_audio"])
        manifest["референс_текст"] = open(cfg["ref_text"], encoding="utf-8").read().strip()
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"\nпротокол: {os.path.join(out, 'manifest.json')}")


if __name__ == "__main__":
    main()
