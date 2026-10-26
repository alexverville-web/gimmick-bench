#!/bin/bash
# Double-click to open the Gimmick Bench launcher (macOS).
cd "$(dirname "$0")/.." || exit 1
PY=""
for c in ./runtime/python/bin/python3 python3 /usr/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  osascript -e 'display dialog "Gimmick Bench needs Python 3.9 or newer. macOS will now offer to install the Command Line Tools, which include it. Run Gimmick Bench again afterwards." buttons {"OK"}'
  xcode-select --install
  exit 1
fi
exec "$PY" -m gimmick_bench ui
