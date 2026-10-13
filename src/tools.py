"""Поиск внешних программ, нужных сборке.

Приложение запускается из Finder, а там PATH голый: ни /opt/homebrew/bin,
ни /usr/local/bin. Поэтому ffmpeg ищется по известным местам, а не берётся
из окружения. Когда его нет вовсе -- об этом говорится внятно, а не
падением с FileNotFoundError.
"""
import os
import shutil

МЕСТА = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/opt/local/bin")


def найти(имя, внутри_бандла=None):
    """Путь к программе. Сначала своя копия в приложении, потом система."""
    if внутри_бандла and os.path.exists(внутри_бандла):
        return внутри_бандла
    из_пути = shutil.which(имя)
    if из_пути:
        return из_пути
    for d in МЕСТА:
        p = os.path.join(d, имя)
        if os.access(p, os.X_OK):
            return p
    return None


def ffmpeg(root=None):
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    свой = os.path.join(root, "Resources", "ffmpeg") if root else None
    p = найти("ffmpeg", свой)
    if not p:
        from ui import т
        raise RuntimeError(т("не найден ffmpeg"))
    return p


def прочитать_wav(путь, sr=24000):
    import numpy as np, soundfile as sf
    y, исходная = sf.read(путь, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    if исходная != sr and len(y):
        n = int(round(len(y) * sr / исходная))
        y = np.interp(np.linspace(0, len(y) - 1, n), np.arange(len(y)), y).astype("float32")
    return y
