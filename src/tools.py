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
    свой = os.path.join(root, "Resources", "ffmpeg") if root else None
    p = найти("ffmpeg", свой)
    if not p:
        raise RuntimeError(
            "не найден ffmpeg — он нужен, чтобы упаковать звук.\n"
            "Установите его: brew install ffmpeg")
    return p
