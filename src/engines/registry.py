"""Описание движков синтеза: что каждому нужно, чтобы заработать.

Приложение читает это описание и доставляет недостающее по требованию --
когда человек выбрал голос. Ничего не ставится заранее и ничего не
трогается в системном Python: у каждого движка своё окружение в
~/Library/Application Support/Overlay/engines/<имя>.
"""
import os
import sys

SUPPORT = os.path.expanduser("~/Library/Application Support/Overlay")
ENGINES_DIR = os.path.join(SUPPORT, "engines")

ENGINES = {
    "apple": {
        "название": "Системный голос",
        "описание": "Голоса macOS. Мгновенно, подсветка по словам.",
        "языки": ["ru", "en"],
        # Сам синтез делает система, но книгу всё равно надо разобрать и
        # собрать -- для этого нужны те же библиотеки, что и остальным.
        "python": "3.13",
        "пакеты": ["ebooklib", "beautifulsoup4", "soundfile", "numpy", "tqdm",
                   "imageio-ffmpeg"],
        "модели": [],
        "правки": [],
        "клонирование": False,
        "пословно": True,
    },
    "qwen": {
        "название": "Qwen3-TTS",
        "python": "3.13",
        "описание": "Клонирование голоса по образцу. Медленно, но точно.",
        "языки": ["ru", "en"],
        # 0.5.3: появился непрерывный батчинг (до 9x против 2.9x по одному)
        # и исправлена та ошибка с encoder_config, ради которой был патч.
        "пакеты": ["mlx-audio==0.5.3", "soundfile", "numpy", "ebooklib",
                   "beautifulsoup4", "tqdm", "imageio-ffmpeg"],
        "модели": [("mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit", 2.9)],
        "правки": [],
        "батч": True,
        "клонирование": True,
        "пословно": False,
    },
    "kokoro": {
        "название": "Kokoro",
        "описание": "Быстрее реального времени. Готовые голоса, без клонирования.",
        "языки": ["en"],
        # misaki объявляет requires_python <3.13, поэтому окружению нужен
        # интерпретатор постарше -- ради этого движки и разведены по своим.
        "python": "3.10",
        "пакеты": ["mlx-audio==0.3.1", "misaki[en]", "soundfile", "numpy",
                   "ebooklib", "beautifulsoup4", "tqdm", "imageio-ffmpeg"],
        # 4-битная сборка не подходит к этой версии mlx-audio: в её весах
        # свёртки транспонированы, загрузка падает на predictor.F0.
        "модели": [("mlx-community/Kokoro-82M-bf16", 0.33)],
        "правки": [],
        "клонирование": False,
        "пословно": False,
    },
    "kokoro-ru": {
        "название": "Kokoro русская",
        "описание": "Русская речь с расстановкой ударений, ~10x быстрее "
                    "реального времени на процессоре.",
        "языки": ["ru"],
        # Автор модели пишет: "works with the stock kokoro package,
        # unmodified" -- это PyTorch, не MLX. Фонемизатор свой, ru_g2p.py из
        # того же репозитория (ударения через RUAccent), а не misaki.
        "python": "3.10",
        "пакеты": ["kokoro", "torch", "ruaccent", "soundfile", "numpy",
                   "ebooklib", "beautifulsoup4", "tqdm", "imageio-ffmpeg"],
        "модели": [("zaakirio/kokoro-ru", 0.33)],
        # espeak-data обязателен: без него espeak молча игнорирует знаки
        # ударения, и русская речь выходит хуже базовой -- об этом сам
        # ru_g2p.py и сообщает при запуске.
        "файлы": [("zaakirio/kokoro-ru", "ru_g2p.py"),
                  ("zaakirio/kokoro-ru", "kokoro-config.json"),
                  ("zaakirio/kokoro-ru", "config.json")],
        "каталоги": [("zaakirio/kokoro-ru", "espeak-data")],
        "правки": [],
        "клонирование": False,
        "пословно": False,
        "runtime": "torch",
    },
}

# Разборщики PDF: превращают страницы в текст со структурой. Ставятся так
# же, как движки синтеза -- каждый в своё окружение, по требованию.
PARSERS = {
    "docling": {
        "название": "Docling",
        "python": "3.13",
        "описание": "IBM, ML-разметка страницы: тело, колонтитулы, картинки.",
        # ocrmac -- доступ к Vision из macOS: им распознаются сканы.
        "пакеты": ["docling", "ocrmac"],
        "вес": 1.5,
        # Распознавание только на страницах без текстового слоя: на
        # остальных оно ничего не даёт, а стоит десятикратного замедления
        # (31 с против 3.3 с на 16 страницах, при том же результате).
        # Скан Vision читает за ~0.65 с на страницу, ошибаясь примерно в
        # одном слове на страницу (10 стр. Latour: 11 слов из ~3700).
        "ocr": "сканы",
        "по умолчанию": True,
    },
}


def env_dir(engine):
    return os.path.join(ENGINES_DIR, engine)


def env_python(engine):
    """Путь к интерпретатору окружения движка (может ещё не существовать)."""
    return os.path.join(env_dir(engine), "bin", "python3")


def is_ready(engine):
    return (os.path.exists(env_python(engine))
            and not os.path.exists(os.path.join(env_dir(engine), ".installing")))
