import os

АНГЛ = os.environ.get("OVERLAY_UI_LANG", "ru").startswith("en")

EN = {
    "ставлю разборщик PDF": "installing the PDF parser",
    "не удалось поставить разборщик PDF": "could not install the PDF parser",
    "ставлю распознавание сканов": "installing scan recognition",
    "разбираю PDF": "parsing the PDF",
    "беру уже разобранный PDF: {имя}": "reusing the parsed PDF: {имя}",
    "в PDF нет текста, и распознать его не удалось":
        "the PDF has no text and it could not be recognized",
    "не удалось разобрать PDF": "could not parse the PDF",
    "нет такого файла: {путь}": "no such file: {путь}",
    "нет такого голоса: {имя}": "no such voice: {имя}",
    "прежняя работа не подходит ({голос}), начинаю заново":
        "previous work does not match ({голос}), starting over",
    "книга:    {имя}": "book:     {имя}",
    "язык:     {язык}": "language: {язык}",
    "голос:    {имя} ({движок}, быстрый синтез)": "voice:    {имя} ({движок}, fast synthesis)",
    "голос:    {имя} (системный, подсветка по словам)":
        "voice:    {имя} (system, word highlighting)",
    "голос:    {имя} (пресет)": "voice:    {имя} (preset)",
    "голос:    {имя}": "voice:    {имя}",
    "темп:     {темп}x": "speed:    {темп}x",
    "папка:    {папка}": "folder:   {папка}",
    "результат: {что}": "result:   {что}",
    "аудиокнига и EPUB": "audiobook and EPUB",
    "аудиокнига": "audiobook",
    "EPUB с подсветкой": "EPUB with highlighting",
    "ставлю движок {движок}": "installing engine {движок}",
    "движок {движок} не установился": "engine {движок} failed to install",
    "ставлю ffmpeg": "installing ffmpeg",
    "синтез": "synthesis",
    "сборка": "assembling",
    "сборка EPUB": "EPUB assembly",
    "сборка книги с подсветкой": "building the highlighted book",
    "сборка аудиокниги": "building the audiobook",
    "{этап}: остановлено": "{этап}: stopped",
    "код {код}": "exit code {код}",
    "американский": "American",
    "британский": "British",
    "жен.": "female",
    "муж.": "male",
    "русский": "Russian",
    "распознаю текст: страниц без текстового слоя {n} из {всего}":
        "recognizing text: {n} of {всего} pages have no text layer",
    "разбор PDF": "parsing the PDF",
    "книга собралась бы битой ({n})": "the book would be corrupted ({n})",
    "книга собралась бы повреждённой: {файл}": "the book would be corrupted: {файл}",
    "{этап}: озвучено {сделано} из {всего} фрагментов, прогон прерван — "
    "запустите снова, чтобы продолжить":
        "{этап}: narrated {сделано} of {всего} fragments, the run was interrupted — "
        "start it again to continue",
    "Qwen пакетом": "Qwen (batched)",
    "синтез остановился: процесс движка аварийно завершился":
        "synthesis stopped: the engine process crashed",
    "не найден appletts; соберите его: app/build.sh":
        "appletts not found; build it with app/build.sh",
    "для движка {движок} не задана модель": "no model set for engine {движок}",
    "не найден ffmpeg": "ffmpeg not found",
    "нет интерпретатора Python {версия} для движка {движок}":
        "no Python {версия} interpreter for engine {движок}",
    "создаю окружение": "creating the environment",
    "ставлю библиотеки закреплённых версий ({n})": "installing pinned libraries ({n})",
    "ставлю библиотеки ({n})": "installing libraries ({n})",
    "скачиваю модель {repo} ({гб} ГБ)": "downloading model {repo} ({гб} GB)",
    "беру {имя}": "fetching {имя}",
    "уже установлен": "already installed",
    "Системный голос": "System voice",
    "Голоса macOS. Мгновенно, подсветка по словам.":
        "macOS voices. Instant, word-by-word highlighting.",
    "Клонирование голоса по образцу. Медленно, но точно.":
        "Clones a voice from a sample. Slow but accurate.",
    "Быстрее реального времени. Готовые голоса, без клонирования.":
        "Faster than real time. Ready-made voices, no cloning.",
    "Kokoro русская": "Kokoro Russian",
    "Русская речь с расстановкой ударений, ~10x быстрее реального времени на процессоре.":
        "Russian speech with stress marks, ~10x faster than real time on the CPU.",
    "IBM, ML-разметка страницы: тело, колонтитулы, картинки.":
        "IBM, ML page layout: body text, running heads, figures.",
}


def т(текст, **поля):
    if АНГЛ:
        текст = EN.get(текст, текст)
    return текст.format(**поля) if поля else текст
