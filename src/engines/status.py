"""Что установлено, что можно скачать. Для окна настроек."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from registry import ENGINES, PARSERS, env_dir, is_ready   # noqa: E402


def размер(путь):
    если = 0
    for d, _, files in os.walk(путь):
        for f in files:
            try:
                если += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return если


def main():
    вывод = []
    for имя, оп in {**ENGINES, **PARSERS}.items():
        if имя == "apple":
            continue
        d = env_dir(имя)
        готов = is_ready(имя)
        вывод.append({
            "имя": имя,
            "название": оп.get("название", имя),
            "описание": оп.get("описание", ""),
            "установлен": готов,
            "гб_на_диске": round(размер(d) / 2**30, 2) if готов else 0,
            "гб_скачать": оп.get("вес") or round(
                sum(s for _, s in оп.get("модели", [])) + 1.2, 1),
            "клонирование": оп.get("клонирование", False),
            "батч": оп.get("батч", False),
            "языки": оп.get("языки", []),
        })
    print(json.dumps(вывод, ensure_ascii=False))


if __name__ == "__main__":
    main()
