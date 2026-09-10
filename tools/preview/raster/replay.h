/* The watchface's four draw passes, in one place.
 *
 * canvas_update_proc in src/c/main.c draws the stroke as: a black clear, an
 * antialiased filled path, an antialiased 1 px outline of the same path, and a
 * hard 1 px minute core with antialiasing switched off. Each line below
 * corresponds to one line there; nothing is re-derived.
 *
 * It lives in a header shared by both drivers -- the one that gets its geometry
 * from main.c and the one that gets an arbitrary polygon on stdin -- so the two
 * cannot drift into replaying the passes differently.
 */
#pragma once

#include "gtypes.h"
#include "gpath.h"
#include "gcontext.h"
#include "graphics.h"

//! Same rounding as main.c's round_coordinate: half away from zero.
static inline GPoint replay_round(float x, float y) {
  return GPoint(x >= 0.0f ? (int16_t)(x + 0.5f) : (int16_t)(x - 0.5f),
                y >= 0.0f ? (int16_t)(y + 0.5f) : (int16_t)(y - 0.5f));
}

//! `core` runs from the pivot to the minute tip; consecutive duplicates are
//! skipped and the last point is set directly, exactly as
//! draw_minute_pixel_core does.
static void replay_passes(GContext *ctx, GPoint *polygon, uint32_t polygon_count,
                          const GPoint *core, int core_count) {
  GPathInfo info = { .num_points = polygon_count, .points = polygon };
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

  gpath_destroy(path);

  /* pass 4 -- the hard one-pixel minute core */
  if (core_count > 0) {
    graphics_context_set_antialiased(ctx, false);
    graphics_context_set_stroke_color(ctx, GColorWhite);
    graphics_context_set_stroke_width(ctx, 1);
    GPoint previous = core[0];
    for (int i = 1; i < core_count; ++i) {
      if (!gpoint_equal(&core[i], &previous)) {
        graphics_draw_line(ctx, previous, core[i]);
      }
      previous = core[i];
    }
    graphics_draw_pixel(ctx, previous);
    graphics_context_set_antialiased(ctx, true);
  }
}
