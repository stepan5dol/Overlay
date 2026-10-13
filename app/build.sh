#!/bin/bash
set -e
cd "$(dirname "$0")"
OUT="${THORIUM_BUILD_DIR:-$(mktemp -d)}"
APP="$OUT/Overlay.app"
REPO="$(cd .. && pwd)"
REPO_HINT="${THORIUM_KEEP_REPO_PATH:+$REPO}"
PYTHON="${THORIUM_PYTHON:-@BUNDLE@/python/3.13/bin/python3}"
MIN_OS="14.0"

[ -x python/3.10/bin/python3 ] && [ -x python/3.13/bin/python3 ] || ./fetch_python.sh

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -parse-as-library Overlay.swift Settings.swift -o "$APP/Contents/MacOS/Overlay" \
       -target "arm64-apple-macos$MIN_OS"
swiftc -O AppleTTS.swift -o appletts -target "arm64-apple-macos$MIN_OS"

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
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleLocalizations</key><array><string>en</string><string>ru</string></array>
  <key>LSMinimumSystemVersion</key><string>$MIN_OS</string>
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

R="$APP/Contents/Resources"
cp AppIcon.icns appletts "$R/"
cp -R en.lproj ru.lproj "$R/"
mkdir -p "$R/python" "$R/src" "$R/refs"
for v in 3.10 3.13; do
  rsync -a --exclude "__pycache__" "python/$v" "$R/python/"
done
rsync -a --exclude "__pycache__" --exclude "out" --exclude "*.pyc" ../src/ "$R/src/"
rsync -a --exclude "vakhshtayn.*" ../refs/ "$R/refs/"
cp ../README.md ../LICENSE "$R/"

xattr -cr "$APP"
codesign --force --deep -s - "$APP"
codesign --verify --deep --strict "$APP"

if [ "${THORIUM_NO_INSTALL:-}" != "1" ]; then
  pkill -x Overlay 2>/dev/null || true
  sleep 1
  rm -rf /Applications/Overlay.app
  mv "$APP" /Applications/
  APP=/Applications/Overlay.app
fi
echo "готово: $APP"
