import os, sys, time, glob
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import warnings; warnings.filterwarnings("ignore")

REF = "/Users/stepandolzhenko/Downloads/ebook2audiobook/voices/__sessions/voice-2c940a01-ffda-4a74-ab49-f5b8f1be3739/rus/ref_active.wav"
OUT = "/Users/stepandolzhenko/Documents/Thorium 2.0/out/exp/smoke"
MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit"

t0 = time.time()
from mlx_audio.tts.utils import load_model
from mlx_audio.tts.generate import generate_audio
print(f"импорт {time.time()-t0:.1f}s", flush=True)

t0 = time.time()
model = load_model(MODEL)
print(f"загрузка модели {time.time()-t0:.1f}s", flush=True)

t0 = time.time()
generate_audio(
    model=model,
    text="Проверка связи. Первое предложение звучит именно так.",
    ref_audio=REF, ref_text=None,
    language="Russian", lang_code="ru",
    output_path=OUT, audio_format="wav", file_prefix="smoke",
    verbose=False, temperature=0.8, top_p=0.8, repetition_penalty=1.0,
)
print(f"генерация {time.time()-t0:.1f}s", flush=True)
print("файлы:", glob.glob(OUT + "/**/*.wav", recursive=True), flush=True)
