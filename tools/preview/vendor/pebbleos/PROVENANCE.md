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

## Caveat

This is Core Devices' current firmware, not the SDK's emulator image. The
rasterizer here is unchanged from the original Pebble Technology code on every
point the harness depends on, but a device or emulator running older firmware
may differ.
