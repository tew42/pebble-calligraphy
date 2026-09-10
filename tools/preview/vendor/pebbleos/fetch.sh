#!/usr/bin/env bash
# Re-vendor the PebbleOS graphics sources. Overwrites everything under fw/ and
# include/. See PROVENANCE.md.
set -euo pipefail
PIN=6e9c7c29e1fd78ecb899127c5c6f28f33e5d1488
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

git clone --filter=blob:none --no-checkout https://github.com/coredevices/PebbleOS.git "$tmp/src"
git -C "$tmp/src" checkout "$PIN" -- src include lib tests/test_images LICENSE

rm -rf "$here/fw" "$here/include" "$here/lib" "$here/tests"
mkdir -p "$here/fw/applib/graphics" "$here/fw/util" "$here/fw/board/displays" \
         "$here/include/pbl/util" "$here/lib/util" "$here/tests/test_images"
for f in gpath.c graphics_line.c graphics_private.c graphics_private_raw.c gtypes.c \
         gpath.h graphics_line.h graphics_private.h graphics_private_raw.h gtypes.h \
         gcolor_definitions.h; do
  cp "$tmp/src/src/fw/applib/graphics/$f" "$here/fw/applib/graphics/$f"
done
for f in swap.h bitset.h bitset.c; do cp "$tmp/src/src/fw/util/$f" "$here/fw/util/$f"; done
cp "$tmp/src/src/fw/board/display.h" "$here/fw/board/display.h"
for f in display_qemu_emery.h display_qemu_gabbro.h; do
  cp "$tmp/src/src/fw/board/displays/$f" "$here/fw/board/displays/$f"
done
for f in math.c trig.c; do cp "$tmp/src/lib/util/$f" "$here/lib/util/$f"; done
for f in gpath_filled_crossing_aa gpath_filled_duplicates_aa \
         gpath_filled_single_duplicate_aa gpath_filled_aa gpath_filled_bolt_aa; do
  cp "$tmp/src/tests/test_images/$f.8bit.png" "$here/tests/test_images/"
done
for f in attributes.h math.h math_fixed.h trig.h; do
  cp "$tmp/src/include/pbl/util/$f" "$here/include/pbl/util/$f"
done
cp "$tmp/src/LICENSE" "$here/LICENSE"
echo "re-vendored at $PIN"
