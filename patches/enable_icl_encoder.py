"""Enable ICL voice cloning in mlx-audio.

The Qwen3-TTS loader parses decoder_config from the speech tokenizer's
config.json but never parses encoder_config: the variable is initialised to
None and passed straight to the constructor. The tokenizer therefore reports
has_encoder=False even though both the config entry and the 225 encoder
tensors are present in the checkpoint -- and because generate() gates ICL on
has_encoder, every cloning call silently falls back to speaker-embedding-only
conditioning.

Applies the missing parse. Re-run after reinstalling mlx-audio.
"""
import sys
from pathlib import Path

TARGET = ("mlx_audio/tts/models/qwen3_tts/qwen3_tts.py")
OLD = """                if "decoder_config" in tokenizer_config_dict:
                    filtered = filter_dict_for_dataclass(
                        Qwen3TTSTokenizerDecoderConfig,
                        tokenizer_config_dict["decoder_config"],
                    )
                    decoder_config = Qwen3TTSTokenizerDecoderConfig(**filtered)
"""
NEW = OLD + """
                if "encoder_config" in tokenizer_config_dict:
                    filtered = filter_dict_for_dataclass(
                        Qwen3TTSTokenizerEncoderConfig,
                        tokenizer_config_dict["encoder_config"],
                    )
                    encoder_config = Qwen3TTSTokenizerEncoderConfig(**filtered)
"""
IMPORT_OLD = "from .config import filter_dict_for_dataclass"
IMPORT_NEW = ("from .config import (filter_dict_for_dataclass,\n"
              "                     Qwen3TTSTokenizerEncoderConfig)")


def main(site_packages):
    p = Path(site_packages) / TARGET
    s = p.read_text()
    if "Qwen3TTSTokenizerEncoderConfig(**filtered)" in s:
        print("уже применён"); return 0
    if OLD not in s:
        print("не найден целевой фрагмент — библиотека изменилась", file=sys.stderr)
        return 1
    s = s.replace(OLD, NEW).replace(IMPORT_OLD, IMPORT_NEW)
    p.write_text(s)
    print(f"применён к {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
