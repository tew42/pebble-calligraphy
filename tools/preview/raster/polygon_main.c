/* Rasterizes a polygon supplied on stdin, using the watchface's own draw passes.
 *
 * The workshop sheets build some candidate envelopes in Python rather than by
 * patching main.c -- the bisector-tangent comparison, for one, reconstructs the
 * offset from a denser sampling of the same curve. This lets those candidates be
 * drawn by the firmware rasterizer too, so a Python-built variant and a
 * C-built one are judged on exactly the same pipeline.
 *
 *   frame <polygon_count> <core_count>
 *   <polygon_count pairs of float x y>   <core_count pairs of float x y>
 *
 * Coordinates are rounded with main.c's own rule, so passing the unrounded
 * floats here matches what vec2_to_gpoint would have produced.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "replay.h"

#define MAX_POINTS 4096

static uint8_t s_framebuffer[DISP_COLS * DISP_ROWS];
static GPoint s_polygon[MAX_POINTS];
static GPoint s_core[MAX_POINTS];

int main(void) {
  GContext context;
  int polygon_count, core_count;

  /* The leading space matters: literal characters in a scanf format do not
     skip whitespace, so without it the 'f' would be matched against the newline
     left by the previous frame and only the first frame would ever be read. */
  while (scanf(" frame %d %d", &polygon_count, &core_count) == 2) {
    if (polygon_count < 2 || polygon_count > MAX_POINTS ||
        core_count < 0 || core_count > MAX_POINTS) {
      fprintf(stderr, "bad counts %d %d\n", polygon_count, core_count);
      return 1;
    }
    for (int i = 0; i < polygon_count; ++i) {
      float x, y;
      if (scanf("%f %f", &x, &y) != 2) return 1;
      s_polygon[i] = replay_round(x, y);
    }
    for (int i = 0; i < core_count; ++i) {
      float x, y;
      if (scanf("%f %f", &x, &y) != 2) return 1;
      s_core[i] = replay_round(x, y);
    }

    graphics_context_init(&context, s_framebuffer);
    replay_passes(&context, s_polygon, (uint32_t)polygon_count,
                  s_core, core_count);
    fwrite(s_framebuffer, 1, sizeof(s_framebuffer), stdout);
  }
  return 0;
}
