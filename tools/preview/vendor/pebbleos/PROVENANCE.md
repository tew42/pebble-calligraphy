# Vendored PebbleOS graphics sources

Pinned to upstream commit:

    6e9c7c29e1fd78ecb899127c5c6f28f33e5d1488

from https://github.com/coredevices/PebbleOS (Apache-2.0, SPDX
`FileCopyrightText: 2024 Google LLC` on every file).

## Why these files

The watchface's visible edge is produced entirely by the firmware rasterizer,
and its behaviour is not documented — in two places the published SDK docs are
actively wrong about it. Reimplementing it from prose produced renders that
disagreed with the emulator. These are the routines `canvas_update_proc`
actually reaches:

| file | what it provides |
| --- | --- |
| `fw/applib/graphics/gpath.c` | `gpath_draw_filled`, `gpath_draw_outline`; the paired up/down crossing lists that make the fill rule nonzero; the 1 px span erosion |
| `fw/applib/graphics/graphics_line.c` | the four line rasterizers, incl. the 1 px Wu-Xiang AA line that draws the outline |
| `fw/applib/graphics/graphics_private.c` | span writers and `graphics_private_set_pixel` |
| `fw/applib/graphics/graphics_private_raw.c` | `g_default_draw_implementation` — the per-pixel blend that quantizes coverage to four levels |
| `fw/applib/graphics/gtypes.c` | `gcolor_blend` and the 4096-entry blending lookup table |
| `lib/util/math.c` | `integer_sqrt`, which the stroked-line geometry calls |
| `lib/util/trig.c` | `sin_lookup`/`cos_lookup` -- a 257-entry quarter-wave table with linear interpolation. Vendored rather than approximated with libm, which would move pixels on 22 of the 720 displayed minutes |
| `tests/test_images/gpath_filled*_aa.8bit.png` | the firmware's own expected rasterizer output, from its unit-test suite. `check_raster.py` reproduces the geometry of five of these cases and diffs pixel for pixel |
| `fw/board/display.h` + `fw/board/displays/display_qemu_{emery,gabbro}.h` | the authoritative platform description: emery 200x228 rectangular, gabbro 260x260 round, both 8-bit colour. Selected with `-DCONFIG_BOARD_QEMU_EMERY` or `-DCONFIG_BOARD_QEMU_GABBRO`, so the dimensions and `PBL_COLOR`/`PBL_RECT` come from the firmware rather than from me |

Headers are vendored only where the .c files need the real definitions
(`gtypes.h` and friends). `gcontext.h`, `graphics.h` and the platform headers
are *not* vendored — upstream's versions pull in text layout, resources and
PNG decoding. Minimal stand-ins live in `tools/preview/raster/shim/`.

## Refreshing

Run `./fetch.sh` to re-vendor. It re-clones at the pin above; change `PIN`
in that script to move to a newer upstream, then re-run
`tools/preview/check_raster.py` — its expectations were derived from this
commit's arithmetic and a rasterizer change upstream should make them fail
rather than pass quietly.

## What this verifies, and what it does not

`check_raster.py` renders five of the firmware's own gpath test fixtures --
including a self-crossing path, a path with duplicate points, a degenerate
two-point path, and two cases with a clip box -- and matches the committed
reference images **bit for bit, 0 of 45,600 pixels differing** on each. That
covers the filled path: the scanline structure, the nonzero fill rule, the span
erosion, the four-level blend, and clipping.

There is **no** committed reference for an antialiased 1 px line at 8-bit
colour: the `draw_line_*` fixtures are all for `asterix`, which is a 1-bit
mono board where antialiasing is compiled out entirely. The outline pass is
therefore verified two weaker ways -- the vendored line rasterizer is
unmodified, and every shim function it reaches is one the bit-exact fill
fixtures also exercise -- plus source-derived predictions about where it skips
antialiasing, which `check_raster.py` asserts.

## Caveat

This is Core Devices' current firmware, not the SDK's emulator image. The
rasterizer here is unchanged from the original Pebble Technology code on every
point the harness depends on, but a device or emulator running older firmware
may differ.
