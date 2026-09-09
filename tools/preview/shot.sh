#!/usr/bin/env bash
# Rasterize the exploration sheets so they can actually be looked at.
set -euo pipefail
CHROME="${CHROME:-/opt/pw-browsers/chromium-1194/chrome-linux/chrome}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for name in "$@"; do
  svg="$here/out/$name.svg"
  w=$(sed -n '1s/.*width="\([0-9.]*\)".*/\1/p' "$svg")
  h=$(sed -n '1s/.*height="\([0-9.]*\)".*/\1/p' "$svg")
  "$CHROME" --headless --no-sandbox --disable-gpu --hide-scrollbars \
    --window-size="${w%.*}","$((${h%.*}+90))" \
    --screenshot="$here/out/$name.png" "file://$svg" 2>/dev/null
  echo "$name -> ${w%.*}x${h%.*}"
done
