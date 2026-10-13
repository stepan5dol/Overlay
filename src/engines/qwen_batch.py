"""Синтез Qwen пакетом: несколько фрагментов за один проход модели.

Веса модели читаются из памяти один раз на весь пакет, а не на каждый
фрагмент, — отсюда прирост.

С образцом голоса пакет считается своим циклом, а не сессией mlx-audio.
Сессия (0.5.3–0.5.6) не передаёт ref_audio в модель, и фрагменты выходили
случайным голосом; вдобавок на каждом шаге она склеивает кэш всех
фрагментов пакета и режет его обратно. Свой цикл: фрагменты группируются
по длине, кэш один на пакет, штраф за повторы считается на GPU, с
процессором сверяемся раз в несколько шагов, закончившиеся фрагменты
выкидываются из пакета. На статье (64 фрагмента, M4 Max): сессия 248 с,
batch_generate из библиотеки 184 с, свой цикл 116 с. Пакет больше 8 не
ускоряет: 16 -- те же 116 с, 32 -- 135 с.

Пресетные голоса (CustomVoice) идут прежней сессией: образца у них нет.

Протокол как у остальных помощников: строки JSON на входе, строки JSON на
выходе.
"""
import argparse, json, os, sys, time

SR = 24000
# Как у библиотеки в режиме клонирования: без сильного штрафа длинный
# образец в начале последовательности тянет модель в повторы.
ШТРАФ, ОКНО_ШТРАФА = 1.5, 64
TOP_K = 50
СВЕРКА = 8          # шагов между проверками, закончились ли фрагменты
СЖАТИЕ = 0.25       # доля закончившихся, после которой пакет ужимается


def штраф_за_повторы(mx, logits, hist, vocab):
    """Штраф по окну последних токенов, без обращения к процессору.

    hist [B, окно] -- последние токены; пустые места заполнены vocab, это
    лишний столбец маски, который тут же отрезается.
    """
    маска = mx.zeros((logits.shape[0], vocab + 1), dtype=mx.bool_)
    маска = mx.put_along_axis(маска, hist, mx.array(True), axis=-1)[:, :vocab]
    lg = logits[:, -1, :]
    штраф = mx.where(lg < 0, lg * ШТРАФ, lg / ШТРАФ)
    return mx.where(маска, штраф, lg)[:, None, :]


def группа_с_образцом(m, тексты, ref_audio, ref_text, lang, temperature, top_p):
    """Один пакет с клонированием голоса. Отдаёт (номер в группе, звук)."""
    import mlx.core as mx
    import numpy as np

    cfg = m.config.talker_config
    eos, vocab = cfg.codec_eos_token_id, cfg.vocab_size
    suppress = m._suppress_codec_tokens(eos)
    bi = m._prepare_batch_inputs(тексты, language=lang, ref_audio=ref_audio,
                                 ref_text=ref_text, return_metadata=True)
    B = len(тексты)
    # потолок длины как у библиотеки: зациклившийся фрагмент не съест прогон
    предел = [min(4096, max(75, len(m.tokenizer.encode(t)) * 6)) for t in тексты]
    T0 = bi.attention_mask.shape[1]
    шагов = max(предел)

    строки = list(range(B))                    # строка пакета -> номер в группе
    emb, trailing, pad = bi.input_embeds, bi.trailing_text_hidden, bi.tts_pad_embed
    # маска внимания выделяется сразу на всю длину и дальше только режется
    amask = mx.concatenate([bi.attention_mask, mx.ones((B, шагов + 1))], axis=1)
    cache = m.talker.make_cache()
    code_cache = m.talker.code_predictor.make_cache()
    finished = mx.zeros((B,), dtype=mx.bool_)
    count = mx.zeros((B,), dtype=mx.int32)
    limit = mx.array(предел, dtype=mx.int32)
    t_idx = mx.zeros((B, 1), dtype=mx.int32)
    hist = mx.full((B, ОКНО_ШТРАФА), vocab, dtype=mx.int32)
    накоплено = []                             # (коды [b, 16], годен [b]) по шагам
    коды = [[] for _ in range(B)]

    def слить():
        if not накоплено:
            return
        c = mx.stack([x for x, _ in накоплено])            # [S, b, 16]
        v = np.array(mx.stack([y for _, y in накоплено]))  # [S, b]
        for b, r in enumerate(строки):
            idx = np.nonzero(v[:, b])[0]
            if len(idx):
                коды[r].append(c[mx.array(idx), b])
        накоплено.clear()

    for step in range(шагов):
        logits, hidden = m.talker(emb, cache=cache,
                                  attention_mask=amask[:, :T0 + step])
        tok = m._sample_token_batch(штраф_за_повторы(mx, logits, hist, vocab),
                                    temperature=temperature, top_k=TOP_K,
                                    top_p=top_p, repetition_penalty=1.0,
                                    suppress_tokens=suppress)
        tok = mx.where(finished[:, None], mx.array(eos, dtype=tok.dtype), tok)
        finished = finished | (tok[:, 0] == eos)
        code_tokens, all_codes = m._predict_code_tokens(
            tok, hidden, temperature=temperature, top_k=TOP_K, top_p=top_p,
            code_cache=code_cache)
        годен = ~finished
        накоплено.append((all_codes, годен))
        count = count + годен.astype(mx.int32)
        hist = mx.concatenate(
            [hist[:, 1:], mx.where(годен, tok[:, 0], vocab)[:, None]], axis=1)
        finished = finished | (count >= limit)
        emb = m._next_batch_input_embeds(trailing, pad, t_idx, code_tokens,
                                         pad_when_index_clamped=True)
        t_idx = t_idx + (~finished).astype(mx.int32)[:, None]
        # GPU считает следующий шаг, пока Python строит граф
        mx.async_eval(emb, finished, count, hist, all_codes)

        if step % СВЕРКА != СВЕРКА - 1:
            continue
        конец = finished.tolist()
        if all(конец):
            break
        if sum(конец) >= max(1, int(len(строки) * СЖАТИЕ)):
            слить()
            keep = [b for b, f in enumerate(конец) if not f]
            ki = mx.array(keep)
            for c in cache:
                c.keys, c.values = c.keys[ki], c.values[ki]
            emb, trailing, t_idx = emb[ki], trailing[ki], t_idx[ki]
            finished, count, limit = finished[ki], count[ki], limit[ki]
            hist, amask = hist[ki], amask[ki]
            строки = [строки[b] for b in keep]
    слить()

    # Декодер слышит образец перед фрагментом, как в библиотеке: так стык
    # звучит тем же голосом. Образец потом отрезается.
    ref_t = mx.transpose(bi.ref_codes, (0, 2, 1))
    ref_len = bi.ref_codes.shape[2]
    for r in range(B):
        if not коды[r]:
            yield r, np.zeros(0, dtype=np.float32)
            continue
        full = mx.concatenate(
            [ref_t, mx.concatenate(коды[r], axis=0)[None]], axis=1)
        audio, lens = m.speech_tokenizer.decode(full)
        audio = audio[0]
        n = int(lens[0])
        if 0 < n < audio.shape[0]:
            audio = audio[:n]
        cut = int(ref_len / full.shape[1] * audio.shape[0])
        yield r, np.array(audio[cut:], dtype=np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref-audio")
    ap.add_argument("--ref-text")
    ap.add_argument("--voice")
    ap.add_argument("--model", default="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lang-code", default="en")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-p", type=float, default=0.8)
    args = ap.parse_args()

    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import warnings; warnings.filterwarnings("ignore")
    import numpy as np, soundfile as sf
    from mlx_audio.tts.utils import load_model
    from mlx_audio.tts.continuous import TTSBatchItem, TTSBatchOptions

    m = load_model(args.model)
    ref_text = (open(args.ref_text, encoding="utf-8").read().strip()
                if args.ref_text else None)
    if args.ref_audio and not getattr(
            getattr(m, "speech_tokenizer", None), "has_encoder", False):
        sys.exit("ICL недоступен: у токенизатора речи нет энкодера")

    задания = [json.loads(l) for l in sys.stdin if l.strip()]
    if not задания:
        return

    def ответить(з, звук, ошибка=None):
        if ошибка or звук is None:
            ответ = {"id": з["id"], "error": (ошибка or "пусто")[:160]}
        else:
            sf.write(os.path.join(args.out, з["id"] + ".wav"), звук, SR)
            ответ = {"id": з["id"], "seconds": len(звук) / SR}
        print(json.dumps(ответ, ensure_ascii=False), flush=True)

    if args.ref_audio:
        from mlx_audio.utils import load_audio
        образец = load_audio(args.ref_audio, sample_rate=SR)
        # Похожие по длине фрагменты -- в один пакет: короткие не ждут
        # длинный, пока тот договорит.
        длина = [len(m.tokenizer.encode(з["text"])) for з in задания]
        порядок = sorted(range(len(задания)), key=lambda i: -длина[i])
        for start in range(0, len(порядок), args.batch):
            группа = [задания[i] for i in порядок[start:start + args.batch]]
            отвечено = set()
            try:
                for r, звук in группа_с_образцом(
                        m, [з["text"] for з in группа], образец, ref_text,
                        args.lang_code, args.temperature, args.top_p):
                    ответить(группа[r], звук)
                    отвечено.add(r)
            except Exception as e:
                # Сбой пакета не должен молча съесть его фрагменты: каждый
                # получает ответ, и narrate.py засчитает прогон неполным.
                for r, з in enumerate(группа):
                    if r not in отвечено:
                        ответить(з, None, f"{type(e).__name__}: {e}")
        return

    opts = TTSBatchOptions(max_batch_size=args.batch,
                           temperature=args.temperature, top_p=args.top_p,
                           lang_code=args.lang_code)
    сессия = m.create_tts_batch_session(opts)
    по_номеру = {}
    for i, з in enumerate(задания):
        по_номеру[i] = з
        сессия.add([TTSBatchItem(sequence_id=i, text=з["text"],
                                 voice=args.voice)])

    готово = 0
    # Ждём не от начала прогона, а от последнего результата: иначе на
    # длинной книге таймаут срабатывает посреди работы и помощник молча
    # выходит, оставляя книгу наполовину озвученной.
    последний_успех = time.time()
    while готово < len(задания):
        события = сессия.step()
        if not события:
            if time.time() - последний_успех > 600:
                print(json.dumps({"id": "", "error": "движок молчит 10 минут"},
                                 ensure_ascii=False), flush=True)
                break
            continue
        for ev in события:
            if not (ev.done or ev.error):
                continue
            з = по_номеру[ev.sequence_id]
            звук = (None if ev.error or ev.audio is None
                    else np.array(ev.audio, dtype=np.float32).reshape(-1))
            ответить(з, звук, str(ev.error) if ev.error else None)
            готово += 1
            последний_успех = time.time()


if __name__ == "__main__":
    main()
