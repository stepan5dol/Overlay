#!/bin/bash
# Собирает Thorium.app. Приложение — тонкая оболочка: вся работа в src/book.py,
# поэтому бандл должен лежать внутри репозитория (он ищет корень на два уровня вверх).
set -e
cd "$(dirname "$0")"
APP="Overlay.app"
REPO="$(cd .. && pwd)"
PYTHON="${THORIUM_PYTHON:-/Users/stepandolzhenko/qwen3-tts-apple-silicon/.venv/bin/python}"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -parse-as-library Overlay.swift -o "$APP/Contents/MacOS/Overlay" \
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
  <key>ThoriumRepoRoot</key><string>$REPO</string>
  <key>ThoriumPython</key><string>$PYTHON</string>
  <key>CFBundleDocumentTypes</key><array><dict>
    <key>CFBundleTypeName</key><string>EPUB</string>
    <key>CFBundleTypeRole</key><string>Viewer</string>
    <key>LSItemContentTypes</key><array><string>org.idpf.epub-container</string></array>
  </dict></array>
</dict></plist>
PLIST

[ -f AppIcon.icns ] && cp AppIcon.icns "$APP/Contents/Resources/"
codesign --force --deep -s - "$APP" 2>/dev/null || true
# Ставим сразу: собранное, но не установленное приложение -- источник
# путаницы, окно продолжает работать по старой версии.
if [ "${THORIUM_NO_INSTALL:-}" != "1" ]; then
  pkill -x Overlay 2>/dev/null || true
  sleep 1
  rm -rf "/Applications/$APP"
  cp -R "$APP" /Applications/
  echo "установлено: /Applications/$APP"
fi
echo "собрано: $(pwd)/$APP"
