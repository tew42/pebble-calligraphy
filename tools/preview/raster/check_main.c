/* Drives the vendored rasterizer with hand-made geometry, so the shim can be
 * checked against predictions made by reading the firmware source. Reads
 * commands on stdin and dumps the framebuffer as one digit per pixel (0 = black
 * through 3 = white), which is all check_raster.py needs.
 *
 *   band <x0> <width> <lean> <rows> <aa>   filled parallelogram
 *   line <x0> <y0> <x1> <y1> <aa>          1 px outline segment
 *   fixture <name> <aa>                    reproduce a firmware unit-test fixture
 *
 * The fixture command exists so the harness can be diffed against the
 * firmware's own expected output. tests/fw/graphics/test_graphics_gpath.template.c
 * draws these paths and compares the result to a committed reference image; the
 * geometry and draw state here are transcribed from that test, so if this shim
 * reproduces the reference byte for byte then the harness rasterizes the way
 * the firmware's own test suite says it should.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gtypes.h"
#include "gpath.h"
#include "gcontext.h"
#include "graphics.h"

static uint8_t s_framebuffer[DISP_COLS * DISP_ROWS];

static int level_of(uint8_t v) {
  switch (v) {
    case 0xC0: return 0;
    case 0xD5: return 1;
    case 0xEA: return 2;
    case 0xFF: return 3;
    default: return 9;   /* off-palette; check_raster.py fails on any of these */
  }
}

static void dump(const char *label) {
  printf("# %s\n", label);
  for (int y = 0; y < DISP_ROWS; ++y) {
    for (int x = 0; x < DISP_COLS; ++x) {
      putchar('0' + level_of(s_framebuffer[y * DISP_COLS + x]));
    }
    putchar('\n');
  }
}

static void clear(GContext *ctx) {
  graphics_context_init(ctx, s_framebuffer);
  graphics_context_set_fill_color(ctx, GColorBlack);
  graphics_fill_rect(ctx, &ctx->dest_bitmap.bounds);
}

int main(void) {
  GContext context;
  GContext *ctx = &context;
  char verb[32];

  while (scanf("%31s", verb) == 1) {
    if (strcmp(verb, "band") == 0) {
      int x0, width, lean, rows, aa;
      if (scanf("%d %d %d %d %d", &x0, &width, &lean, &rows, &aa) != 5) break;
      clear(ctx);
      GPoint points[4] = {
        GPoint(x0, 0),
        GPoint(x0 + lean, rows),
        GPoint(x0 + width + lean, rows),
        GPoint(x0 + width, 0),
      };
      GPathInfo info = { .num_points = 4, .points = points };
      GPath *path = gpath_create(&info);
      graphics_context_set_antialiased(ctx, aa != 0);
      graphics_context_set_fill_color(ctx, GColorWhite);
      gpath_draw_filled(ctx, path);
      gpath_destroy(path);
      char label[96];
      snprintf(label, sizeof label, "band x0=%d width=%d lean=%d rows=%d aa=%d",
               x0, width, lean, rows, aa);
      dump(label);
    } else if (strcmp(verb, "line") == 0) {
      int x0, y0, x1, y1, aa;
      if (scanf("%d %d %d %d %d", &x0, &y0, &x1, &y1, &aa) != 5) break;
      clear(ctx);
      graphics_context_set_antialiased(ctx, aa != 0);
      graphics_context_set_stroke_color(ctx, GColorWhite);
      graphics_context_set_stroke_width(ctx, 1);
      graphics_draw_line(ctx, GPoint(x0, y0), GPoint(x1, y1));
      char label[96];
      snprintf(label, sizeof label, "line %d,%d-%d,%d aa=%d", x0, y0, x1, y1, aa);
      dump(label);
    } else if (strcmp(verb, "fixture") == 0) {
      char name[64];
      int aa;
      if (scanf("%63s %d", name, &aa) != 2) break;

      /* Geometry, placement and clip boxes transcribed from the firmware
       * test. SCREEN_WIDTH/HEIGHT there are 144x168 and are used only for
       * positioning; the framebuffer is DISP_COLS x DISP_ROWS. */
      const int16_t SCREEN_WIDTH = 144, SCREEN_HEIGHT = 168;
      GPoint crossing[6] = { GPoint(0, 40), GPoint(20, 20), GPoint(60, 60),
                             GPoint(80, 40), GPoint(60, 20), GPoint(20, 60) };
      GPoint duplicates[6] = { GPoint(40, 0), GPoint(40, 0), GPoint(0, 40),
                               GPoint(0, 40), GPoint(80, 40), GPoint(80, 40) };
      GPoint single_duplicate[2] = { GPoint(40, 0), GPoint(40, 0) };
      GPoint house[11] = { GPoint(-40, 0), GPoint(0, -40), GPoint(40, 0),
                           GPoint(28, 0), GPoint(28, 40), GPoint(10, 40),
                           GPoint(10, 16), GPoint(-10, 16), GPoint(-10, 40),
                           GPoint(-28, 40), GPoint(-28, 0) };
      GPoint bolt[6] = { GPoint(21, 0), GPoint(14, 26), GPoint(28, 26),
                         GPoint(7, 60), GPoint(14, 34), GPoint(0, 34) };

      GPathInfo info;
      GPoint offset = GPoint(0, 0);
      bool half_clip = false;
      if (strcmp(name, "crossing") == 0) {
        info = (GPathInfo){ .num_points = 6, .points = crossing };
      } else if (strcmp(name, "duplicates") == 0) {
        info = (GPathInfo){ .num_points = 6, .points = duplicates };
        half_clip = true;
      } else if (strcmp(name, "single_duplicate") == 0) {
        info = (GPathInfo){ .num_points = 2, .points = single_duplicate };
      } else if (strcmp(name, "house") == 0) {
        info = (GPathInfo){ .num_points = 11, .points = house };
        offset = GPoint(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2);
      } else if (strcmp(name, "bolt") == 0) {
        info = (GPathInfo){ .num_points = 6, .points = bolt };
        half_clip = true;
      } else {
        fprintf(stderr, "unknown fixture: %s\n", name);
        return 1;
      }

      graphics_context_init(ctx, s_framebuffer);
      /* framebuffer_clear memsets 0xff -- white */
      memset(s_framebuffer, 0xff, sizeof(s_framebuffer));
      if (half_clip) {
        ctx->draw_state.clip_box = GRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT / 2);
      }
      GPath *path = gpath_create(&info);
      gpath_rotate_to(path, 0);
      gpath_move_to(path, offset);
      graphics_context_set_antialiased(ctx, aa != 0);
      graphics_context_set_fill_color(ctx, GColorBlack);
      gpath_draw_filled(ctx, path);
      gpath_destroy(path);

      /* Fixtures are not white-on-black, so dump raw bytes as hex. */
      printf("# fixture %s aa=%d\n", name, aa);
      for (int y = 0; y < DISP_ROWS; ++y) {
        for (int x = 0; x < DISP_COLS; ++x) {
          printf("%02x", s_framebuffer[y * DISP_COLS + x]);
        }
        putchar('\n');
      }
    } else {
      fprintf(stderr, "unknown verb: %s\n", verb);
      return 1;
    }
  }
  return 0;
}
