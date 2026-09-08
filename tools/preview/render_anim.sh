#!/usr/bin/env bash
# Rasterize an animation frame sequence and encode it as a GIF.
#
#   python3 report.py --anim          # emit the frames
#   ./render_anim.sh anim-current     # rasterize + encode
#
# Kept out of report.py so the Python harness stays dependency-free and
# importable; this is the only part that needs external binaries.
set -euo pipefail

CHROME="${CHROME:-/opt/pw-browsers/chromium-1194/chrome-linux/chrome}"
# ffmpeg is not used: the bundled build has no GIF encoder (see gifwriter.py).
SCALE="${SCALE:-1}"

name="${1:-anim-current}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dir="$here/out/anim/$name"
manifest="$dir/manifest.txt"

for binary in "$CHROME"; do
  if [ ! -x "$binary" ]; then
    echo "not executable: $binary" >&2
    echo "override with CHROME=... $0 $name" >&2
    exit 1
  fi
done
[ -f "$manifest" ] || { echo "no manifest at $manifest -- run: python3 report.py --anim" >&2; exit 1; }

field() { awk -v k="$1" '$1==k {print $2}' "$manifest"; }
frames=$(field frames); fps=$(field fps)
width=$(field width);   height=$(field height)
out_w=$(( width * SCALE ))
out_h=$(( height * SCALE ))

png="$dir/png"
rm -rf "$png"; mkdir -p "$png"
echo "rasterizing $frames frames at ${out_w}x${out_h} ..."

for i in $(seq 0 $((frames - 1))); do
  n=$(printf '%04d' "$i")
  cat > "$dir/wrap.html" <<HTML
<body style="margin:0;background:#16191d"><img src="file://$dir/frame-$n.svg"
 style="display:block;width:${out_w}px;height:${out_h}px"></body>
HTML
  "$CHROME" --headless --disable-gpu --no-sandbox --hide-scrollbars \
    --screenshot="$png/frame-$n.png" --window-size="$out_w,$out_h" \
    "file://$dir/wrap.html" 2>/dev/null
  printf '\r  %d/%d' "$((i + 1))" "$frames"
done
rm -f "$dir/wrap.html"
echo

gif="$here/out/$name.gif"
echo "encoding $gif at ${fps} fps ..."
# The bundled ffmpeg is a stripped Playwright build with no GIF encoder, so the
# PNG -> GIF step is done by gifwriter.py (standard library only).
python3 "$here/gifwriter.py" "$png" "$gif" "$fps"
