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
        "пакеты": [],                       # ничего не нужно
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
                   "beautifulsoup4", "tqdm"],
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
                   "ebooklib", "beautifulsoup4", "tqdm"],
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
                   "ebooklib", "beautifulsoup4", "tqdm"],
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
    "pymupdf4llm": {
        "название": "PyMuPDF4LLM",
        "python": "3.12",
        "описание": "Быстрый, без нейросетей. Хорош на простой вёрстке.",
        "пакеты": ["pymupdf4llm"],
        "вес": 0.1,
    },
    "docling": {
        "название": "Docling",
        "python": "3.13",
        "описание": "IBM, ML-разметка страницы: тело, колонтитулы, картинки.",
        "пакеты": ["docling"],
        "вес": 1.5,
        # Распознавание текста на картинках нам не нужно -- книга и так с
        # текстовым слоем, -- а стоит оно десятикратного замедления:
        # 31 с против 3.3 с на 16 страницах, при том же результате.
        "ocr": False,
        "по умолчанию": True,
    },
    "marker": {
        "название": "Marker",
        "python": "3.13",
        "описание": "Точная структура и картинки. Лицензия ограничивает "
                    "коммерческое применение.",
        "пакеты": ["marker-pdf"],
        "вес": 2.5,
        # Не запускается: surya требует бинарник llama-server вне Python.
        "работает": False,
    },
    "mineru": {
        "название": "MinerU",
        "python": "3.13",
        "описание": "Сложная вёрстка и формулы, лучший на научных статьях.",
        "пакеты": ["mineru"],
        "вес": 2.0,
    },
}


def env_dir(engine):
    return os.path.join(ENGINES_DIR, engine)


def env_python(engine):
    """Путь к интерпретатору окружения движка (может ещё не существовать)."""
    if engine == "apple":
        return sys.executable            # системному голосу python не нужен
    return os.path.join(env_dir(engine), "bin", "python3")


def is_ready(engine):
    return engine == "apple" or os.path.exists(env_python(engine))
