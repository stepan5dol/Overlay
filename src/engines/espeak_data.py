import os
import shutil
import tempfile


def короткий_путь(data, имя="overlay-espeak-data"):
    if len(os.path.realpath(data)) < 120:
        return data
    копия = os.path.join(tempfile.gettempdir(), имя)
    if not os.path.exists(os.path.join(копия, "phontab")):
        shutil.copytree(data, копия, dirs_exist_ok=True)
    return копия


def укоротить_misaki():
    try:
        import espeakng_loader
        from misaki import espeak  # noqa: F401
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
    except ImportError:
        return
    EspeakWrapper.set_data_path(
        короткий_путь(espeakng_loader.get_data_path(), "overlay-espeak-ng-data"))
