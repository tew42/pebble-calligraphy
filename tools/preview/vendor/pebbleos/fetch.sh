#!/usr/bin/env bash
# Re-vendor the PebbleOS graphics sources. Overwrites everything under fw/ and
# include/. See PROVENANCE.md.
set -euo pipefail
PIN=6e9c7c29e1fd78ecb899127c5c6f28f33e5d1488
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

git clone --filter=blob:none --no-checkout https://github.com/coredevices/PebbleOS.git "$tmp/src"
git -C "$tmp/src" checkout "$PIN" -- src include LICENSE

rm -rf "$here/fw" "$here/include"
mkdir -p "$here/fw/applib/graphics" "$here/fw/util" "$here/include/pbl/util"
for f in gpath.c graphics_line.c graphics_private.c graphics_private_raw.c gtypes.c \
         gpath.h graphics_line.h graphics_private.h graphics_private_raw.h gtypes.h \
         gcolor_definitions.h; do
  cp "$tmp/src/src/fw/applib/graphics/$f" "$here/fw/applib/graphics/$f"
done
for f in swap.h bitset.h bitset.c; do cp "$tmp/src/src/fw/util/$f" "$here/fw/util/$f"; done
for f in attributes.h math.h math_fixed.h trig.h; do
  cp "$tmp/src/include/pbl/util/$f" "$here/include/pbl/util/$f"
done
cp "$tmp/src/LICENSE" "$here/LICENSE"
echo "re-vendored at $PIN"
