#!/usr/bin/env python3
"""Compile the watchface's geometry path on its own, and measure what it costs.

    python3 tools/preview/check_c_build.py [repeats]

`main.c` can only be built properly by the Pebble SDK, which is a slow way to
find out that a geometry edit does not compile.  Everything from the top of the
file down to `build_centerline` / `build_stroke_polygon` touches only six Pebble
symbols, so this stubs those, compiles the rest with `-Wall -Wextra`, and runs
the whole per-minute rebuild for all 720 hand positions.

It reports the square-root and division counts because `square_root_float()` is
the dominant arithmetic in a rebuild, and those counts are the only numbers here
that mean anything on the watch -- the wall time is a desktop figure.

Needs a C compiler.  Use it as a smoke test before an SDK build, and to check
that a change to the geometry has not quietly multiplied the work.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

MAIN_C = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "src", "c", "main.c")

#: Where the geometry ends and the Pebble-facing half of the file begins.
GEOMETRY_ENDS_AT = ("/* ---------------------------------------------------"
                    "---------------------- */\n/* Geometry cache")

STUB = r"""
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <time.h>
#include <math.h>
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* The six Pebble symbols the geometry path touches. */
#define TRIG_MAX_ANGLE 0x10000
#define TRIG_MAX_RATIO 0xffff

typedef struct { int16_t x, y; } GPointStorage;
#define GPoint(a, b) ((GPointStorage){ (int16_t)(a), (int16_t)(b) })
typedef GPointStorage GPoint;
typedef struct { int16_t w, h; } GSize;
typedef struct { GPointStorage origin; GSize size; } GRect;
typedef struct Layer Layer;
typedef struct Window Window;
typedef struct GPath GPath;
typedef struct { uint32_t num_points; GPoint *points; } GPathInfo;

static int32_t sin_lookup(int32_t angle) {
  return (int32_t)(sin((double)angle * 2.0 * M_PI / TRIG_MAX_ANGLE)
                   * TRIG_MAX_RATIO);
}

static int32_t cos_lookup(int32_t angle) {
  return (int32_t)(cos((double)angle * 2.0 * M_PI / TRIG_MAX_ANGLE)
                   * TRIG_MAX_RATIO);
}

static long g_square_roots = 0;
static long g_divisions = 0;
"""

DRIVER = r"""
int main(int argc, char **argv) {
  const int repeats = argc > 1 ? atoi(argv[1]) : 50;
  const Vec2 center = make_vec2(100.0f, 114.0f);
  const float maximum_radius = 100.0f;
  long checksum = 0;

  initialize_solver_workspace();

  struct timespec started, finished;
  clock_gettime(CLOCK_MONOTONIC, &started);
  for (int pass = 0; pass < repeats; ++pass) {
    for (int hour = 0; hour < 12; ++hour) {
      for (int minute = 0; minute < 60; ++minute) {
        const CenterlineResult result =
          build_centerline(
            center,
            maximum_radius,
            hour_to_pebble_angle(hour, minute),
            minute_to_pebble_angle(minute)
          );
        build_stroke_polygon(
          result.pivot_index,
          result.waist_opening
        );
        checksum +=
          s_polygon_points[10].x +
          s_polygon_points[60].y +
          result.pivot_index;
      }
    }
  }
  clock_gettime(CLOCK_MONOTONIC, &finished);

  const double seconds =
    (finished.tv_sec - started.tv_sec) +
    1e-9 * (finished.tv_nsec - started.tv_nsec);
  const long rebuilds = 720L * repeats;

  printf("%ld rebuilds (720 hand positions x %d)\n", rebuilds, repeats);
  printf("  square roots   %.1f per rebuild\n",
         (double)g_square_roots / rebuilds);
  printf("  divisions in them %.1f per rebuild\n",
         (double)g_divisions / rebuilds);
  printf("  desktop time   %.1f us per rebuild\n",
         1e6 * seconds / rebuilds);
  printf("  checksum       %ld\n", checksum);
  return 0;
}
"""


def main() -> int:
    source = open(MAIN_C).read()
    try:
        cut = source.index(GEOMETRY_ENDS_AT)
    except ValueError:
        print("FAIL: could not find the geometry/cache boundary in main.c")
        return 1

    body = source[:cut].replace("#include <pebble.h>", "", 1)

    # Count the work without changing it.
    marker = "  for (int iteration = 0; iteration < 3; ++iteration) {"
    if marker not in body:
        print("FAIL: square_root_float no longer has the expected shape; "
              "the instrumentation needs updating")
        return 1
    body = body.replace(
        marker,
        "  ++g_square_roots;\n\n" + marker + "\n    ++g_divisions;", 1)

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "geometry.c")
        open(path, "w").write(STUB + body + DRIVER)
        binary = os.path.join(directory, "geometry")
        # Unused-function warnings are expected: the Pebble-facing half of the
        # file is not compiled here, so its callees look dead.
        build = subprocess.run(
            ["gcc", "-std=c11", "-Wall", "-Wextra", "-O2",
             "-Wno-unused-function", "-Wno-unused-variable",
             "-o", binary, path, "-lm"],
            capture_output=True, text=True)
        if build.returncode != 0:
            print("FAIL: the geometry path does not compile")
            print(build.stderr)
            return 1
        if build.stderr.strip():
            print("warnings from the geometry path:")
            print(build.stderr)
        print("the geometry path compiles clean on its own")
        run = subprocess.run([binary, sys.argv[1] if len(sys.argv) > 1
                              else "50"], capture_output=True, text=True)
        if run.returncode != 0:
            print("FAIL: the geometry path crashed")
            print(run.stderr)
            return 1
        print(run.stdout, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
