"""Синтез русской Kokoro. Запускается интерпретатором своего окружения.

Модель идёт не через mlx-audio, а через официальный пакет kokoro на
PyTorch -- так указано автором. Фонемизатор свой, ru_g2p, он же расставляет
ударения через RUAccent: без них "за́мок" и "замо́к" звучат одинаково.

Протокол тот же, что у системного синтеза: на вход строки JSON
{"id", "text"}, на выход {"id", "seconds"} либо {"id", "error"}.
"""
import json, os, sys

REPO = "zaakirio/kokoro-ru"
CHECKPOINTS = {"sveta": "kokoro-ru-v2-base.pth",
               "masha": "kokoro-ru-v2-base.pth",
               "dima": "kokoro-ru-v2-dima.pth"}
SR = 24000


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default="sveta")
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args()

    if args.voice not in CHECKPOINTS:
        sys.exit(f"голос {args.voice} неизвестен; есть: {', '.join(CHECKPOINTS)}")

    # ru_g2p и espeak-data лежат рядом с окружением движка
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
    import torch, soundfile as sf
    from kokoro import KModel
    from huggingface_hub import hf_hub_download
    from ru_g2p import RuG2P

    g2p = RuG2P()
    model = KModel(repo_id=REPO,
                   model=hf_hub_download(REPO, CHECKPOINTS[args.voice])).eval()
    pack = torch.load(hf_hub_download(REPO, f"voices/{args.voice}.pt"),
                      map_location="cpu", weights_only=False)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        task = json.loads(line)
        path = os.path.join(args.out, task["id"] + ".wav")
        try:
            ipa, oov = g2p(task["text"])
            with torch.no_grad():
                audio = model(ipa, pack[len(ipa) - 1], args.speed,
                              return_output=True).audio
            a = audio.cpu().numpy()
            sf.write(path, a, SR)
            out = {"id": task["id"], "seconds": len(a) / SR}
            if oov:
                out["неизвестные_слова"] = list(oov)[:5]
        except Exception as e:
            out = {"id": task["id"], "error": str(e)[:160]}
        print(json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
