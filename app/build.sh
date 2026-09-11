#!/bin/bash
# Собирает Thorium.app. Приложение — тонкая оболочка: вся работа в src/book.py,
# поэтому бандл должен лежать внутри репозитория (он ищет корень на два уровня вверх).
set -e
cd "$(dirname "$0")"
APP="Overlay.app"
REPO="$(cd .. && pwd)"
# В раздаваемом образе путь к каталогу разработчика не нужен: конвейер
# лежит внутри бандла. Оставляем его только при сборке для себя.
REPO_HINT="${THORIUM_KEEP_REPO_PATH:+$REPO}"
# Интерпретатор для конвейера. По умолчанию -- окружение движка, которое
# приложение создаёт само; переопределяется через THORIUM_PYTHON.
# Интерпретатор указывает внутрь бандла; при разработке переопределяется
# через THORIUM_PYTHON.
# Служебный интерпретатор приложения -- на нём же ставятся движки.
PYTHON="${THORIUM_PYTHON:-@BUNDLE@/python/3.13/bin/python3}"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -parse-as-library Overlay.swift Settings.swift -o "$APP/Contents/MacOS/Overlay" \
       -target arm64-apple-macos26.0

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Overlay</string>
  <key>CFBundleDisplayName</key><string>Overlay</string>
  <key>CFBundleIdentifier</key><string>local.overlay.maker</string>
  <key>CFBundleExecutable</key><string>Overlay</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>26.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>ThoriumRepoRoot</key><string>$REPO_HINT</string>
  <key>ThoriumPython</key><string>$PYTHON</string>
  <key>ThoriumBundled</key><true/>
  <key>CFBundleDocumentTypes</key><array><dict>
    <key>CFBundleTypeName</key><string>EPUB</string>
    <key>CFBundleTypeRole</key><string>Viewer</string>
    <key>LSItemContentTypes</key><array><string>org.idpf.epub-container</string></array>
  </dict></array>
</dict></plist>
PLIST

[ -f AppIcon.icns ] && cp AppIcon.icns "$APP/Contents/Resources/"

# Конвейер кладём внутрь приложения: снаружи он есть только на машине
# разработчика, а бандл должен работать у всех.
# Интерпретаторы внутри приложения: у каждого движка своя версия, а в macOS
# есть только 3.9. Скачиваются через ./fetch_python.sh.
if [ -d python ] && [ -n "$(ls -A python 2>/dev/null)" ]; then
  rsync -a --exclude "__pycache__" python/ "$APP/Contents/Resources/python/"
  echo "  интерпретаторы: $(ls python | tr '\n' ' ')"
else
  echo "  ВНИМАНИЕ: нет интерпретаторов, выполните ./fetch_python.sh" >&2
fi

mkdir -p "$APP/Contents/Resources/src" "$APP/Contents/Resources/refs"
rsync -a --exclude "__pycache__" --exclude "out" --exclude "*.pyc" \
      ../src/ "$APP/Contents/Resources/src/"
rsync -a --exclude "vakhshtayn.*" ../refs/ "$APP/Contents/Resources/refs/"
cp ../README.md ../LICENSE "$APP/Contents/Resources/" 2>/dev/null || true
[ -f appletts ] && cp appletts "$APP/Contents/Resources/"
codesign --force --deep -s - "$APP" 2>/dev/null || true
# Ставим сразу: собранное, но не установленное приложение -- источник
# путаницы, окно продолжает работать по старой версии.
if [ "${THORIUM_NO_INSTALL:-}" != "1" ]; then
  pkill -x Overlay 2>/dev/null || true
  sleep 1
  rm -rf "/Applications/$APP"
  mv "$APP" /Applications/
  echo "установлено: /Applications/$APP"
fi
# Бандл перемещается, а не копируется: копия в репозитории давала второе
# приложение с тем же именем в поиске Spotlight.
echo "готово"
