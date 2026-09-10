#!/bin/bash
# Скачивает самодостаточные интерпретаторы внутрь приложения.
#
# Каждому движку нужна своя версия: Kokoro не ставится выше 3.12 (misaki
# объявляет requires_python <3.13), остальные проверены на 3.13. В macOS
# есть только 3.9, а homebrew или conda у человека может не быть -- поэтому
# интерпретаторы едут вместе с приложением.
#
# Точные номера берутся из выпуска, а не задаются вручную: патч-версии
# меняются, и угаданный номер даёт 404.
set -e
cd "$(dirname "$0")"
NEED="3.10 3.12 3.13"
API="https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"

INFO="$(curl -fsSL "$API")"
TAG="$(echo "$INFO" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')"

for short in $NEED; do
  dest="python/$short"
  if [ -x "$dest/bin/python3" ]; then
    echo "  $short уже есть: $("$dest/bin/python3" -V | cut -d' ' -f2)"
    continue
  fi
  name="$(echo "$INFO" | SHORT="$short" /usr/bin/python3 -c '
import json, os, re, sys
d = json.load(sys.stdin)
short = os.environ["SHORT"]
шаблон = re.compile(rf"cpython-{re.escape(short)}\.(\d+)\+\d+-aarch64-apple-darwin-install_only\.tar\.gz$")
подходящие = []
for a in d["assets"]:
    m = шаблон.match(a["name"])
    if m:
        подходящие.append((int(m.group(1)), a["name"]))
print(max(подходящие)[1] if подходящие else "")')"
  [ -n "$name" ] || { echo "  нет сборки для $short" >&2; continue; }

  tmp="$(mktemp -d)"
  echo "  качаю ${name%%+*}…"
  curl -fsSL "https://github.com/astral-sh/python-build-standalone/releases/download/$TAG/$name" -o "$tmp/py.tar.gz"
  tar xzf "$tmp/py.tar.gz" -C "$tmp"
  mkdir -p python
  chmod -R u+w "$dest" 2>/dev/null || true
  rm -rf "$dest"
  mv "$tmp/python" "$dest"
  rm -rf "$tmp"
  echo "    готово: $("$dest/bin/python3" -V)"
done
echo "итого: $(du -sh python | cut -f1)"
