"""Установка движка: своё окружение, пакеты, модели, правки.

Запускается по требованию, когда человек выбрал голос неустановленного
движка. Ход работы печатается строками ШАГ/ГОТОВ/ОШИБКА, чтобы окно
показывало происходящее.

Ничего не ставится в системный Python и ничего не правится в чужих
каталогах: всё живёт в ~/Library/Application Support/Overlay/engines/<имя>.
"""
import argparse, json, os, subprocess, sys, venv

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from registry import ENGINES, PARSERS, env_dir, env_python, is_ready  # noqa: E402

# Разборщики PDF ставятся тем же способом, что и движки синтеза.
ENGINES = {**ENGINES, **{k: {**v, "модели": [], "правки": [], "языки": []}
                         for k, v in PARSERS.items()}}

ROOT = os.path.dirname(os.path.dirname(HERE))


def say(kind, text):
    print(f"{kind} {text}", flush=True)


def bundled_python(engine):
    """Интерпретатор для окружения движка.

    Движок может требовать свою версию Python: misaki, нужный Kokoro,
    объявляет requires_python <3.13. Ищем запрошенную версию сначала среди
    вложенных в приложение, потом в системе.
    """
    want = ENGINES[engine].get("python")
    if want:
        inside = os.path.join(ROOT, "Resources", "python", want, "bin", "python3")
        if os.path.exists(inside):
            return inside
        from shutil import which
        found = which(f"python{want}")
        if found:
            return found
        say("ОШИБКА", f"нужен Python {want}, его нет в системе")
        sys.exit(1)
    inside = os.path.join(ROOT, "Resources", "python", "bin", "python3")
    return inside if os.path.exists(inside) else sys.executable


def make_env(engine):
    d = env_dir(engine)
    if os.path.exists(env_python(engine)):
        return
    say("ШАГ", "создаю окружение")
    os.makedirs(os.path.dirname(d), exist_ok=True)
    # venv из вложенного интерпретатора: системный Python не трогаем
    subprocess.run([bundled_python(engine), "-m", "venv", "--copies", d],
                   check=True)


def install_packages(engine):
    """Ставит закреплённые версии, если они есть.

    Файл requirements/<движок>.txt -- слепок окружения, на котором движок
    проверенно работает. Без него берутся имена из описания, и тогда
    установка невоспроизводима: через месяц соберётся другое.
    """
    lock = os.path.join(HERE, "requirements", f"{engine}.txt")
    if os.path.exists(lock):
        n = sum(1 for l in open(lock) if l.strip() and not l.startswith("#"))
        say("ШАГ", f"ставлю библиотеки закреплённых версий ({n})")
        cmd = [env_python(engine), "-m", "pip", "install", "-q",
               "--disable-pip-version-check", "-r", lock]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            say("ОШИБКА", r.stderr.strip().splitlines()[-1] if r.stderr else "pip")
            sys.exit(1)
        return

    pkgs = ENGINES[engine]["пакеты"]
    if not pkgs:
        return
    say("ШАГ", f"ставлю библиотеки ({len(pkgs)})")
    cmd = [env_python(engine), "-m", "pip", "install", "-q",
           "--disable-pip-version-check", *pkgs]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        say("ОШИБКА", r.stderr.strip().splitlines()[-1] if r.stderr else "pip")
        sys.exit(1)


def apply_patches(engine):
    for name in ENGINES[engine]["правки"]:
        say("ШАГ", f"применяю правку {name}")
        sp = subprocess.run(
            [env_python(engine), "-c",
             "import mlx_audio, os; "
             "print(os.path.dirname(os.path.dirname(mlx_audio.__file__)))"],
            capture_output=True, text=True).stdout.strip()
        script = os.path.join(ROOT, "patches", f"{name}.py")
        r = subprocess.run([sys.executable, script, sp],
                           capture_output=True, text=True)
        if r.returncode != 0:
            say("ОШИБКА", f"правка {name}: {r.stderr.strip()[:120]}")
            sys.exit(1)


def fetch_models(engine):
    for repo, size in ENGINES[engine]["модели"]:
        say("ШАГ", f"скачиваю модель {repo} ({size:.2f} ГБ)")
        code = ("from huggingface_hub import snapshot_download;"
                f"snapshot_download({repo!r})")
        r = subprocess.run([env_python(engine), "-c", code],
                           capture_output=True, text=True)
        if r.returncode != 0:
            say("ОШИБКА", f"модель {repo}: {r.stderr.strip()[-160:]}")
            sys.exit(1)


def fetch_files(engine):
    """Отдельные файлы из репозитория модели -- например, свой фонемизатор."""
    for repo, name in ENGINES[engine].get("файлы", []):
        say("ШАГ", f"беру {name}")
        code = ("from huggingface_hub import hf_hub_download; import shutil, os;"
                f"p=hf_hub_download({repo!r}, {name!r});"
                f"shutil.copy(p, os.path.join({env_dir(engine)!r}, {name!r}))")
        r = subprocess.run([env_python(engine), "-c", code],
                           capture_output=True, text=True)
        if r.returncode != 0:
            say("ОШИБКА", f"{name}: {r.stderr.strip()[-140:]}")
            sys.exit(1)


def fetch_dirs(engine):
    """Каталоги из репозитория модели -- данные, а не веса."""
    for repo, name in ENGINES[engine].get("каталоги", []):
        say("ШАГ", f"беру {name}")
        code = ("from huggingface_hub import snapshot_download; import shutil, os;"
                f"p=snapshot_download({repo!r}, allow_patterns=[{name+'/*'!r}]);"
                f"dst=os.path.join({env_dir(engine)!r}, {name!r});"
                "shutil.rmtree(dst, ignore_errors=True);"
                f"shutil.copytree(os.path.join(p, {name!r}), dst)")
        r = subprocess.run([env_python(engine), "-c", code],
                           capture_output=True, text=True)
        if r.returncode != 0:
            say("ОШИБКА", f"{name}: {r.stderr.strip()[-140:]}")
            sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("engine", choices=sorted(ENGINES))
    ap.add_argument("--check", action="store_true", help="только проверить")
    args = ap.parse_args()

    if args.check:
        print(json.dumps({"движок": args.engine,
                          "установлен": is_ready(args.engine)},
                         ensure_ascii=False))
        return
    if is_ready(args.engine):
        say("ГОТОВ", "уже установлен")
        return

    make_env(args.engine)
    install_packages(args.engine)
    apply_patches(args.engine)
    fetch_models(args.engine)
    fetch_files(args.engine)
    fetch_dirs(args.engine)
    say("ГОТОВ", ENGINES[args.engine]["название"])


if __name__ == "__main__":
    main()
