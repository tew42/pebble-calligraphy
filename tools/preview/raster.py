#!/usr/bin/env python3
"""Rasterize the watchface the way the watch does, using the watch's own code.

    python3 tools/preview/raster.py            # smoke test, writes out/raster-smoke.svg

Every other renderer in this directory draws vectors: it takes the real polygon
vertices out of `main.c` and then hands them to a browser, which antialiases
every edge analytically at whatever zoom the sheet uses.  The watch does nothing
of the kind.  It runs a scanline fill that erodes each span by a pixel, places
partial coverage on the wrong side of the edge, and quantizes that coverage to
four levels; the visible soft edge comes entirely from a separate 1 px
antialiased outline pass, which itself goes hard at horizontal, vertical and
exactly 45 degrees.  None of that is visible in a vector render, and all of it
lands where the envelope is narrowest.

So this links the extracted geometry from `main.c` against the *firmware's*
rasterizer, vendored under vendor/pebbleos, and returns the framebuffer.  The
geometry still comes from `sheet_envelope.build`, so `overrides` and `patches`
work exactly as they do for the vector sheets -- the same experiment, drawn
honestly.

The geometry is the firmware's too, down to the trigonometry: `sin_lookup` is
a 257-entry quarter-wave table with linear interpolation, and it is vendored
rather than approximated.  That matters more than it sounds -- substituting
libm moves pixels in every single frame, which `check_raster.py` measures.

Needs a C compiler.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_envelope

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "vendor", "pebbleos")
SHIM = os.path.join(HERE, "raster", "shim")

BOARDS = {
    "emery": ("CONFIG_BOARD_QEMU_EMERY", 200, 228),
    "gabbro": ("CONFIG_BOARD_QEMU_GABBRO", 260, 260),
}

# Vendored firmware, unmodified.
VENDORED_SOURCES = [
    os.path.join(VENDOR, "fw", "applib", "graphics", f)
    for f in ("gtypes.c", "gpath.c", "graphics_line.c",
              "graphics_private.c", "graphics_private_raw.c")
] + [os.path.join(VENDOR, "lib", "util", f) for f in ("math.c", "trig.c")]

# Original work: the host-side support the vendored code needs.
SHIM_SOURCES = [os.path.join(SHIM, "shim.c")]

SOURCES = VENDORED_SOURCES + SHIM_SOURCES

# Only check_raster.py uses this, to measure what computing the trig with libm
# instead of the firmware's own table would have cost. It is not linked by
# default; vendor/pebbleos/lib/util/trig.c is.
LIBM_TRIG = os.path.join(HERE, "raster", "trig_libm.c")


def sources(trig="firmware"):
    if trig == "firmware":
        return SOURCES
    if trig == "libm":
        return [s for s in SOURCES if not s.endswith("util/trig.c")] + [LIBM_TRIG]
    raise ValueError(trig)


def cflags(board="emery"):
    macro, _, _ = BOARDS[board]
    return [
        f"-D{macro}=1",
        "-include", os.path.join(SHIM, "pebble_config.h"),
        "-I" + os.path.join(VENDOR, "fw"),
        "-I" + os.path.join(VENDOR, "fw", "applib", "graphics"),
        "-I" + os.path.join(VENDOR, "include"),
        "-I" + SHIM,
    ]


# The geometry half of main.c expects <pebble.h>; give it the real graphics
# headers instead of the fake types the vector stub uses.
STUB = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>

#include "gtypes.h"
#include "gpath.h"
#include "gcontext.h"
#include "graphics.h"
#include "graphics_private.h"
#include "pbl/util/trig.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* sin_lookup and cos_lookup come from the vendored lib/util/trig.c -- the
   firmware's own table, not an approximation of it. */

typedef struct Layer Layer;
typedef struct Window Window;
"""

# Replays canvas_update_proc's four passes in order, with the same colours,
# the same antialias flags and the same stroke widths. Nothing is re-derived:
# each line corresponds to one line of the watchface's own draw routine.
DRIVER = r"""
static uint8_t s_framebuffer[DISP_COLS * DISP_ROWS];

static void draw_minute_core(GContext *ctx, uint8_t pivot_index) {
  if (pivot_index >= CENTERLINE_POINT_COUNT) {
    return;
  }
  graphics_context_set_antialiased(ctx, false);
  graphics_context_set_stroke_color(ctx, GColorWhite);
  graphics_context_set_stroke_width(ctx, 1);

  GPoint previous = vec2_to_gpoint(s_centerline[pivot_index]);
  for (int index = pivot_index + 1; index < CENTERLINE_POINT_COUNT; ++index) {
    const GPoint current = vec2_to_gpoint(s_centerline[index]);
    if (!gpoint_equal(&current, &previous)) {
      graphics_draw_line(ctx, previous, current);
    }
    previous = current;
  }
  graphics_draw_pixel(ctx, previous);
  graphics_context_set_antialiased(ctx, true);
}

int main(int argc, char **argv) {
  FILE *frames = NULL;
  if (argc > 1) {
    frames = fopen(argv[1], "wb");
    if (!frames) { perror("frames"); return 1; }
  }

  initialize_solver_workspace();
  const Vec2 center = make_vec2(DISP_COLS / 2.0f, DISP_ROWS / 2.0f);
  const float maximum_radius = DISP_COLS / 2.0f;

  GContext context;
  int hour, minute;
  while (scanf("%d %d", &hour, &minute) == 2) {
    graphics_context_init(&context, s_framebuffer);
    GContext *ctx = &context;

    const CenterlineResult r = build_centerline(
      center, maximum_radius,
      hour_to_pebble_angle(hour, minute),
      minute_to_pebble_angle(minute));
    update_cumulative_lengths();
    build_stroke_polygon(r.pivot_index, r.center_width_scale);

    GPathInfo info = { .num_points = POLYGON_POINT_COUNT,
                       .points = s_polygon_points };
    GPath *path = gpath_create(&info);

    /* pass 1 -- clear to black */
    graphics_context_set_fill_color(ctx, GColorBlack);
    graphics_fill_rect(ctx, &ctx->dest_bitmap.bounds);

    /* pass 2 -- the filled stroke */
    graphics_context_set_antialiased(ctx, true);
    graphics_context_set_fill_color(ctx, GColorWhite);
    gpath_draw_filled(ctx, path);

    /* pass 3 -- the antialiased outline that puts the eroded pixel back */
    graphics_context_set_stroke_color(ctx, GColorWhite);
    graphics_context_set_stroke_width(ctx, 1);
    gpath_draw_outline(ctx, path);

    /* pass 4 -- the hard one-pixel minute core */
    draw_minute_core(ctx, r.pivot_index);

    gpath_destroy(path);

    /* Per-frame census, so a 720-minute sweep can be compared without moving
       33 MB of framebuffer through a pipe. */
    int level[4] = {0, 0, 0, 0}, other = 0;
    unsigned long hash = 1469598103934665603UL;
    for (int i = 0; i < DISP_COLS * DISP_ROWS; ++i) {
      const uint8_t v = s_framebuffer[i];
      if (v == 0xC0) level[0]++;
      else if (v == 0xD5) level[1]++;
      else if (v == 0xEA) level[2]++;
      else if (v == 0xFF) level[3]++;
      else other++;
      hash = (hash ^ v) * 1099511628211UL;
    }
    printf("T %d %d %u %.6f %.6f %d %d %d %d %d %lu\n",
           hour, minute, r.pivot_index,
           s_cumulative_length[CENTERLINE_POINT_COUNT - 1],
           r.center_width_scale,
           level[0], level[1], level[2], level[3], other, hash);

    if (frames) {
      fwrite(s_framebuffer, 1, sizeof(s_framebuffer), frames);
    }
  }
  if (frames) fclose(frames);
  return 0;
}
"""


def gather(times=None, overrides=None, patches=None, board="emery",
           want_frames=True, extra_cflags=(), trig="firmware"):
    """Render each time and return frames with their framebuffers.

    Each frame is a dict with the same `hour`/`minute`/`pivot`/`scale` keys the
    vector harness uses, plus `census` (pixel counts per grey level), `hash`,
    and `buffer` (bytes, one GColor8 per pixel, row-major) when want_frames.
    """
    _, width, height = BOARDS[board]
    times = list(times or sheet_envelope.TIMES)
    with tempfile.TemporaryDirectory() as directory:
        binary = sheet_envelope.build(
            directory, overrides, patches,
            stub=STUB, driver=DRIVER, name="raster",
            cflags=cflags(board) + list(extra_cflags),
            sources=sources(trig))
        frame_path = os.path.join(directory, "frames.bin") if want_frames else None
        payload = "\n".join(f"{h} {m}" for h, m in times) + "\n"
        result = subprocess.run(
            [binary] + ([frame_path] if frame_path else []),
            input=payload, capture_output=True, text=True, check=True)
        blob = open(frame_path, "rb").read() if frame_path else b""

    stride = width * height
    frames = []
    for line in result.stdout.splitlines():
        f = line.split()
        if f[0] != "T":
            continue
        index = len(frames)
        frames.append(dict(
            hour=int(f[1]), minute=int(f[2]), pivot=int(f[3]),
            total=float(f[4]), scale=float(f[5]),
            census=tuple(int(v) for v in f[6:10]), other=int(f[10]),
            hash=int(f[11]), width=width, height=height,
            buffer=blob[index * stride:(index + 1) * stride] if blob else b""))
    return frames


# Coverage is quantized to four alpha steps, so a white-on-black render can only
# ever contain these four bytes. check_raster.py asserts exactly that.
LEVELS = {0xC0: 0, 0xD5: 1, 0xEA: 2, 0xFF: 3}
GREYS = ("#000000", "#555555", "#aaaaaa", "#ffffff")


def as_levels(frame):
    """The framebuffer as a list of rows of 0..3, ready to draw."""
    width, height, buffer = frame["width"], frame["height"], frame["buffer"]
    return [[LEVELS[b] for b in buffer[y * width:(y + 1) * width]]
            for y in range(height)]


def main() -> int:
    frames = gather(times=[(12, 0), (10, 10)])
    for f in frames:
        print(f"{f['hour']:02d}:{f['minute']:02d}  "
              f"black {f['census'][0]:6d}  1/3 {f['census'][1]:4d}  "
              f"2/3 {f['census'][2]:4d}  white {f['census'][3]:5d}  "
              f"off-palette {f['other']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
