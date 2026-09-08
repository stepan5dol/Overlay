# Образцы голоса

Имя файла — имя чтеца. Рядом с каждым `.wav` лежит `.txt` с расшифровкой:
без неё ICL не включается, и клонирование молча вырождается в слабый
режим по одному эмбеддингу говорящего.

| файл | чтец | язык | источник |
|---|---|---|---|
| `vakhshtayn` | Виктор Вахштайн | ru | запись, предоставленная владельцем проекта |
| `linda_johnson` | Linda Johnson | en | LJSpeech, публичное достояние, расшифровка точная |
| `bryan_ness` | Bryan Ness | en | LibriVox, Short Nonfiction Vol. 001 №7 |
| `meredith_hughes` | Meredith Hughes | en | LibriVox, Short Nonfiction Vol. 001 №4 |

У `linda_johnson` расшифровка взята из корпуса, у остальных английских —
распознана whisper и может содержать ошибки.

По умолчанию: русский — `vakhshtayn`, английский — `linda_johnson`.
