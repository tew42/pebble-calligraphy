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
        "-I" + os.path.join(HERE, "raster"),
    ]


# Coverage is quantized to four alpha steps, so a white-on-black render can only
# ever contain these four bytes. check_raster.py asserts exactly that.
LEVELS = {0xC0: 0, 0xD5: 1, 0xEA: 2, 0xFF: 3}
GREYS = ("#000000", "#555555", "#aaaaaa", "#ffffff")


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
#include "replay.h"

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
static GPoint s_core[CENTERLINE_POINT_COUNT];

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

    const CenterlineResult r = build_centerline(
      center, maximum_radius,
      hour_to_pebble_angle(hour, minute),
      minute_to_pebble_angle(minute));
    update_cumulative_lengths();
    build_stroke_polygon(r.pivot_index, r.waist_opening);

    int core_count = 0;
    if (r.pivot_index < CENTERLINE_POINT_COUNT) {
      for (int i = r.pivot_index; i < CENTERLINE_POINT_COUNT; ++i) {
        s_core[core_count++] = vec2_to_gpoint(s_centerline[i]);
      }
    }
    replay_passes(&context, s_polygon_points, POLYGON_POINT_COUNT,
                  s_core, core_count);

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
           r.waist_opening,
           level[0], level[1], level[2], level[3], other, hash);

    for (int i = 0; i < POLYGON_POINT_COUNT; ++i) {
      printf("P %d %d %d\n", i, s_polygon_points[i].x, s_polygon_points[i].y);
    }

    if (frames) {
      fwrite(s_framebuffer, 1, sizeof(s_framebuffer), frames);
    }
  }
  if (frames) fclose(frames);
  return 0;
}
"""


POLYGON_MAIN = os.path.join(HERE, "raster", "polygon_main.c")
_polygon_binary = None


def render_polygons(specs, board="emery"):
    """Rasterize polygons built in Python, through the same four draw passes.

    `specs` is a sequence of (polygon, core) point lists in framebuffer
    coordinates, unrounded -- the driver applies main.c's own rounding. Returns
    a frame dict per spec, shaped like gather's but without the geometry fields,
    since the caller supplied the geometry.
    """
    global _polygon_binary
    _, width, height = BOARDS[board]
    key = (board,)
    if _polygon_binary is None or _polygon_binary[0] != key:
        directory = tempfile.mkdtemp(prefix="raster-poly-")
        binary = os.path.join(directory, "polygon")
        subprocess.run(["gcc", "-std=gnu11", "-O2", "-w", *cflags(board),
                        "-o", binary, POLYGON_MAIN, *sources(), "-lm"],
                       check=True)
        _polygon_binary = (key, binary)
    binary = _polygon_binary[1]

    payload = []
    for polygon, core in specs:
        payload.append(f"frame {len(polygon)} {len(core)}")
        payload.append(" ".join(f"{x:.6f} {y:.6f}" for x, y in polygon))
        if core:
            payload.append(" ".join(f"{x:.6f} {y:.6f}" for x, y in core))
    blob = subprocess.run([binary], input=("\n".join(payload) + "\n").encode(),
                          capture_output=True, check=True).stdout

    stride = width * height
    frames = []
    for index in range(len(specs)):
        buffer = blob[index * stride:(index + 1) * stride]
        census = [0, 0, 0, 0]
        other = 0
        for byte in buffer:
            level = LEVELS.get(byte)
            if level is None:
                other += 1
            else:
                census[level] += 1
        frames.append(dict(width=width, height=height, buffer=buffer,
                           census=tuple(census), other=other))
    return frames


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
    # build_stroke_polygon prints its instrumented C lines while drawing, which
    # happens before the frame's T summary can be known, so they are held and
    # attached to the frame they belong to.
    frames = []
    pending_centerline, pending_polygon = [], []
    for line in result.stdout.splitlines():
        f = line.split()
        if f[0] == "T":
            index = len(frames)
            current = dict(
                hour=int(f[1]), minute=int(f[2]), pivot=int(f[3]),
                total=float(f[4]), scale=float(f[5]),
                census=tuple(int(v) for v in f[6:10]), other=int(f[10]),
                hash=int(f[11]), width=width, height=height,
                centerline=pending_centerline, polygon=pending_polygon,
                buffer=blob[index * stride:(index + 1) * stride] if blob else b"")
            frames.append(current)
            pending_centerline, pending_polygon = [], []
        elif f[0] == "C":
            # build_stroke_polygon's own loop, instrumented by
            # sheet_envelope.build: x, y, stroke width, polygon width
            pending_centerline.append((float(f[2]), float(f[3]),
                                       float(f[4]), float(f[5])))
        elif f[0] == "P":
            # these come after the T line, so they belong to the last frame
            frames[-1]["polygon"].append((int(f[2]), int(f[3])))
    return frames


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
