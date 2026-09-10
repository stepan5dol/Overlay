#!/bin/bash
# Собирает DMG для раздачи. Приложение не подписано: сертификата Developer ID
# нет, поэтому при первом запуске macOS его блокирует, и снимать карантин
# приходится вручную -- команда есть в файле рядом с приложением.
set -e
cd "$(dirname "$0")"
VERSION="${1:-0.1.0}"
APP="/Applications/Overlay.app"
[ -d "$APP" ] || { echo "нет $APP -- сначала ./build.sh"; exit 1; }

STAGE="$(mktemp -d)"
NAME="Overlay-$VERSION-arm64.dmg"
rm -f "../$NAME"

cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

cat > "$STAGE/Прочти меня.txt" <<'TEXT'
Overlay — книга с синхронной озвучкой.

УСТАНОВКА
Перетащите Overlay в папку Applications.

ПЕРВЫЙ ЗАПУСК
Приложение не подписано сертификатом Apple, поэтому macOS откажется его
открыть. Это ожидаемо. Выполните в Терминале:

    xattr -dr com.apple.quarantine /Applications/Overlay.app

После этого приложение открывается обычным двойным щелчком.

ЧТО ЕЩЁ НУЖНО
  • macOS 26 или новее, Apple Silicon
  • ffmpeg:  brew install ffmpeg
  • голосовой движок — скачивается из самого приложения, в настройках

Исходный код: https://github.com/stepan5dol/Overlay
TEXT

hdiutil create -volname "Overlay $VERSION" -srcfolder "$STAGE" \
    -ov -format UDZO "../$NAME" >/dev/null
rm -rf "$STAGE"
echo "собрано: $NAME ($(du -h "../$NAME" | cut -f1))"
