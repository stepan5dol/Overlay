#!/bin/bash
# Собирает Thorium.app. Приложение — тонкая оболочка: вся работа в src/book.py,
# поэтому бандл должен лежать внутри репозитория (он ищет корень на два уровня вверх).
set -e
cd "$(dirname "$0")"
APP="Thorium.app"
REPO="$(cd .. && pwd)"
PYTHON="${THORIUM_PYTHON:-/Users/stepandolzhenko/qwen3-tts-apple-silicon/.venv/bin/python}"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -parse-as-library Thorium.swift -o "$APP/Contents/MacOS/Thorium" \
       -target arm64-apple-macos14.0

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Thorium</string>
  <key>CFBundleDisplayName</key><string>Thorium</string>
  <key>CFBundleIdentifier</key><string>local.thorium.overlay</string>
  <key>CFBundleExecutable</key><string>Thorium</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
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
echo "собрано: $(pwd)/$APP"
