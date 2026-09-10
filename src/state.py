"""Состояние прогона: что уже сделано и на чём остановились.

Обрыв не должен ни терять работу, ни оставлять мусор. Поэтому прогон
ведёт журнал в state.json рядом с фрагментами: этап, число готовых
фрагментов, отпечаток исходных данных. При следующем запуске той же книги
тем же голосом прогон продолжается с места остановки, а не начинается
заново и не собирается из чужого.
"""
import json, os, time

NAME = "state.json"
ЭТАПЫ = ("извлечение", "синтез", "сборка", "готово")


def path(work):
    return os.path.join(work, NAME)


def load(work):
    try:
        with open(path(work), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(work, **поля):
    """Дописывает поля в состояние. Запись атомарная: обрыв на середине
    записи не оставит испорченный журнал."""
    s = load(work)
    s.update(поля)
    s["обновлено"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(work, exist_ok=True)
    tmp = path(work) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path(work))
    return s


def начать(work, отпечаток):
    """Начало прогона. Если отпечаток не совпал -- прежняя работа не наша."""
    s = load(work)
    if s and s.get("отпечаток") != отпечаток:
        return None
    return save(work, отпечаток=отпечаток, этап=s.get("этап", "извлечение"),
                завершён=False)


def незакончен(work):
    """Что осталось доделать, если прогон обрывался."""
    s = load(work)
    if not s or s.get("завершён"):
        return None
    return s
