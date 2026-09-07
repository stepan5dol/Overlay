# Заметки по окружению

## Референс для клонирования голоса

    /Users/stepandolzhenko/Downloads/ebook2audiobook/voices/__sessions/
      voice-2c940a01-ffda-4a74-ab49-f5b8f1be3739/rus/ref_active.wav

11.20 с, 24000 Hz, моно, PCM_16. Транскрипт (whisper-large-v3-turbo)
сохранён в `out/exp/ref_text.txt` — 215 символов, 29 слов, ~155 слов/мин.

`shorttest.py` брал ref_text из `~/f5_folder/artifacts/ref_active.txt`,
которого больше не существует: аудио и текст референса лежали в разных
местах, и текстовая половина утрачена вместе с каталогом.

## Сломанный ассет в mlx-audio

В закреплённом коммите `mlx-audio` отсутствует каталог
`mlx_audio/stt/models/whisper/assets/`, из-за чего авто-транскрипция
референса падает с FileNotFoundError на `multilingual.tiktoken`.

Лечится добором файлов из openai/whisper:

    A=.venv/lib/python3.13/site-packages/mlx_audio/stt/models/whisper/assets
    mkdir -p "$A"
    for f in multilingual gpt2; do
      curl -sSL -o "$A/$f.tiktoken" \
        "https://raw.githubusercontent.com/openai/whisper/main/whisper/assets/$f.tiktoken"
    done

## Что доступно локально

- `mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit` — в кэше HF, клонирование
- `qwen3-tts-patched/` — 1.7B CustomVoice bf16, 4.2 ГБ, референс не нужен
- книгу собирал `shorttest.py` на `1.7B-Base-8bit`, её в кэше нет
