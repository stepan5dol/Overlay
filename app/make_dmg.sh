#!/bin/bash
set -e
cd "$(dirname "$0")"
VERSION="${1:?версия, например 0.1.5}"
STAGE="$(mktemp -d)"
THORIUM_NO_INSTALL=1 THORIUM_BUILD_DIR="$STAGE" ./build.sh
NAME="Overlay-$VERSION-arm64.dmg"
rm -f "../$NAME"

ln -s /Applications "$STAGE/Applications"

cat > "$STAGE/Read me — Прочти меня.txt" <<'TEXT'
Overlay — a book that reads itself / книга с синхронной озвучкой

REQUIREMENTS
  • Mac with Apple Silicon (M1 or newer), macOS 14 or later
  • Internet on first use: voice engines download from inside the app

INSTALL
Drag Overlay into Applications.

FIRST LAUNCH
Overlay is not signed with an Apple Developer certificate, so macOS blocks it
the first time. Open it once, then go to System Settings → Privacy & Security
and click "Open Anyway". Or run in Terminal:

    xattr -dr com.apple.quarantine /Applications/Overlay.app

—

ЧТО НУЖНО
  • Mac на Apple Silicon (M1 и новее), macOS 14 или новее
  • Интернет при первом запуске: голосовые движки скачиваются из приложения

УСТАНОВКА
Перетащите Overlay в папку «Программы».

ПЕРВЫЙ ЗАПУСК
Приложение не подписано сертификатом Apple, поэтому в первый раз macOS его
заблокирует. Откройте его один раз, затем зайдите в Системные настройки →
Конфиденциальность и безопасность и нажмите «Всё равно открыть». Или
выполните в Терминале:

    xattr -dr com.apple.quarantine /Applications/Overlay.app

https://github.com/stepan5dol/Overlay
TEXT

hdiutil create -volname "Overlay $VERSION" -srcfolder "$STAGE" \
    -ov -format UDZO "../$NAME" >/dev/null
rm -rf "$STAGE"
echo "собрано: $NAME ($(du -h "../$NAME" | cut -f1))"
