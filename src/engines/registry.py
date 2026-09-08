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
        "описание": "Клонирование голоса по образцу. Медленно, но точно.",
        "языки": ["ru", "en"],
        "пакеты": ["mlx-audio==0.3.1", "soundfile", "numpy", "ebooklib",
                   "beautifulsoup4", "tqdm"],
        "модели": [("mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit", 2.9)],
        "правки": ["enable_icl_encoder"],   # без неё клонирование не работает
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

def env_dir(engine):
    return os.path.join(ENGINES_DIR, engine)


def env_python(engine):
    """Путь к интерпретатору окружения движка (может ещё не существовать)."""
    if engine == "apple":
        return sys.executable            # системному голосу python не нужен
    return os.path.join(env_dir(engine), "bin", "python3")


def is_ready(engine):
    return engine == "apple" or os.path.exists(env_python(engine))
