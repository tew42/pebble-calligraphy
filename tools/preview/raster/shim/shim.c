/* Host-side support for the vendored PebbleOS rasterizer.
 *
 * Everything here is original work. It exists so the firmware's own gpath.c,
 * graphics_line.c, graphics_private.c and graphics_private_raw.c can run
 * against a plain host buffer instead of a watch. Where a function stands in
 * for a firmware one, its behaviour is transcribed from upstream rather than
 * reinvented, and the transcription is noted; where a function is unreachable
 * from the watchface's three draw passes, it aborts rather than returning
 * something plausible, because a silently wrong pixel is the one failure mode
 * this whole exercise exists to eliminate.
 */

#include "graphics.h"
#include "gcontext.h"
#include "gtypes.h"
#include "graphics_private.h"
#include "graphics_private_raw.h"
#include "bitblt.h"
#include "applib/applib_malloc.auto.h"
#include "process_management/process_manager.h"
#include "process_state/app_state/app_state.h"
#include "system/passert.h"
#include "pbl/util/math.h"

#include <stdlib.h>
#include <string.h>

/* --- allocation ---------------------------------------------------------
 * The rasterizer allocates two small intersection arrays and a rotated-point
 * buffer per fill, and frees them before returning. */

void *applib_malloc(size_t bytes) { return malloc(bytes); }
void *applib_zalloc(size_t bytes) { return calloc(1, bytes); }
void applib_free(void *pointer) { free(pointer); }

/* --- SDK generation -----------------------------------------------------
 * The watchface is an SDK 3+ app, which is what makes antialiasing default to
 * true and takes gbitmap_get_info's legacy2 branch out of play. */

bool process_manager_compiled_with_legacy2_sdk(void) { return false; }

/* Reached only from that dead legacy2 branch in gbitmap_get_info. */
Heap *app_state_get_heap(void) { WTF; }
bool heap_is_allocated(Heap *heap, void *pointer) { (void)heap; (void)pointer; WTF; }

/* --- bitmap -------------------------------------------------------------- */

//! Transcribed from upstream gbitmap.c: the non-circular branch of
//! prv_gbitmap_get_data_row_info. Both emery and gabbro use the plain
//! GBitmapFormat8Bit, so the circular branch is unreachable.
GBitmapDataRowInfo gbitmap_get_data_row_info(const GBitmap *bitmap, uint16_t y) {
  PBL_ASSERTN(bitmap->info.format != GBitmapFormat8BitCircular);
  return (GBitmapDataRowInfo) {
    .data = (uint8_t *)bitmap->addr + y * bitmap->row_size_bytes,
    .min_x = 0,
    .max_x = grect_get_max_x(&bitmap->bounds) - 1,
  };
}

//! Transcribed from upstream gbitmap.c.
uint8_t gbitmap_get_bits_per_pixel(GBitmapFormat format) {
  switch (format) {
    case GBitmapFormat1Bit:
    case GBitmapFormat1BitPalette:
      return 1;
    case GBitmapFormat2BitPalette:
      return 2;
    case GBitmapFormat4BitPalette:
      return 4;
    case GBitmapFormat8Bit:
    case GBitmapFormat8BitCircular:
      return 8;
  }
  return 0;
}

/* Both reached only from graphics_patch_trace_of_moving_rect, which is a
 * scroll-optimisation the watchface never calls. */
void gbitmap_init_as_sub_bitmap(GBitmap *sub, const GBitmap *base, GRect rect) {
  (void)sub; (void)base; (void)rect; WTF;
}
void bitblt_bitmap_into_bitmap(GBitmap *dest, const GBitmap *src, GPoint offset,
                               GCompOp mode, GColor tint) {
  (void)dest; (void)src; (void)offset; (void)mode; (void)tint; WTF;
}

/* --- context ------------------------------------------------------------- */

void graphics_context_init(GContext *ctx, uint8_t *framebuffer) {
  memset(ctx, 0, sizeof(*ctx));

  ctx->dest_bitmap = (GBitmap) {
    .addr = framebuffer,
    .row_size_bytes = DISP_COLS,
    .bounds = GRect(0, 0, DISP_COLS, DISP_ROWS),
  };
  ctx->dest_bitmap.info.format = GBitmapFormat8Bit;
  ctx->dest_bitmap.info.version = 1;

  ctx->parent_framebuffer = NULL;
  ctx->lock = false;

  /* Transcribed from upstream graphics_context_set_default_drawing_state, with
   * init_mode App (so avoid_text_orphans is false). */
  ctx->draw_state = (GDrawState) {
    .stroke_color = GColorBlack,
    .fill_color = GColorBlack,
    .text_color = GColorWhite,
    .tint_color = GColorWhite,
    .compositing_mode = GCompOpAssign,
    .clip_box = ctx->dest_bitmap.bounds,
    .drawing_box = ctx->dest_bitmap.bounds,
    .antialiased = !process_manager_compiled_with_legacy2_sdk(),
    .stroke_width = 1,
    .draw_implementation = &g_default_draw_implementation,
    .avoid_text_orphans = false,
  };
}

GBitmap *graphics_context_get_bitmap(GContext *ctx) {
  PBL_ASSERTN(ctx);
  return &ctx->dest_bitmap;
}

//! Upstream takes the real framebuffer lock here and sets ctx->lock so that
//! public draw entry points bail out while it is held. The span writers capture
//! and release around every single span, so the flag must be cleared again on
//! release or the second span would be dropped.
GBitmap *graphics_capture_frame_buffer(GContext *ctx) {
  PBL_ASSERTN(ctx);
  ctx->lock = true;
  return &ctx->dest_bitmap;
}

void graphics_release_frame_buffer(GContext *ctx, GBitmap *bitmap) {
  PBL_ASSERTN(ctx);
  PBL_ASSERTN(bitmap == &ctx->dest_bitmap);
  ctx->lock = false;
}

//! Upstream accumulates a dirty rectangle so the display driver can send a
//! partial update. Nothing is being sent anywhere, so this is genuinely a
//! no-op rather than a stub standing in for something.
void graphics_context_mark_dirty_rect(GContext *ctx, GRect rect) {
  (void)ctx; (void)rect;
}

/* --- draw state, transcribed from upstream graphics.c -------------------- */

void graphics_context_set_stroke_color(GContext *ctx, GColor color) {
  PBL_ASSERTN(ctx);
  if (ctx->lock) return;
  ctx->draw_state.stroke_color = gcolor_closest_opaque(color);
}

void graphics_context_set_fill_color(GContext *ctx, GColor color) {
  PBL_ASSERTN(ctx);
  if (ctx->lock) return;
  ctx->draw_state.fill_color = gcolor_closest_opaque(color);
}

void graphics_context_set_text_color(GContext *ctx, GColor color) {
  PBL_ASSERTN(ctx);
  if (ctx->lock) return;
  ctx->draw_state.text_color = gcolor_closest_opaque(color);
}

void graphics_context_set_tint_color(GContext *ctx, GColor color) {
  PBL_ASSERTN(ctx);
  if (ctx->lock) return;
  ctx->draw_state.tint_color = gcolor_closest_opaque(color);
}

void graphics_context_set_compositing_mode(GContext *ctx, GCompOp mode) {
  PBL_ASSERTN(ctx);
  if (ctx->lock) return;
  ctx->draw_state.compositing_mode = mode;
}

void graphics_context_set_stroke_width(GContext *ctx, uint8_t stroke_width) {
  PBL_ASSERTN(ctx);
  if (ctx->lock) return;
  /* A width of zero is ignored, keeping the previous value. */
  if (stroke_width >= 1) {
    ctx->draw_state.stroke_width = stroke_width;
  }
}

void graphics_context_set_antialiased(GContext *ctx, bool enable) {
  PBL_ASSERTN(ctx);
  if (ctx->lock) return;
  ctx->draw_state.antialiased = enable;
}

bool graphics_context_get_antialiased(GContext *ctx) {
  PBL_ASSERTN(ctx);
  return ctx->draw_state.antialiased;
}

/* --- drawing ------------------------------------------------------------- */

//! Transcribed from upstream graphics.c. No antialiasing branch and no
//! rounding: GPoint is already integral, so (10, 10) lights row 10 column 10
//! in the stroke colour, fully opaque.
void graphics_draw_pixel(GContext *ctx, GPoint point) {
  PBL_ASSERTN(ctx);
  if (ctx->lock) return;
  point.x += ctx->draw_state.drawing_box.origin.x;
  point.y += ctx->draw_state.drawing_box.origin.y;
  graphics_private_set_pixel(ctx, point);
}

//! The internal two-argument fill, which gpath.c's non-antialiased span
//! callback uses. Upstream routes it through graphics_fill_round_rect with
//! radius 0; there both the antialiased and non-antialiased paths converge on
//! prv_fill_rect_legacy2 with every corner inset zero, which reduces to this:
//! translate into bitmap space, standardize, clip twice, and fill each row.
void graphics_fill_rect(GContext *ctx, const GRect *rect) {
  PBL_ASSERTN(ctx);
  if (!rect || ctx->lock) {
    return;
  }

  GColor fill_color = ctx->draw_state.fill_color;
  if (gcolor_is_transparent(fill_color)) {
    fill_color = GColorWhite;
  }

  GBitmap *bitmap = graphics_context_get_bitmap(ctx);

  GRect clipped = *rect;
  clipped.origin.x += ctx->draw_state.drawing_box.origin.x;
  clipped.origin.y += ctx->draw_state.drawing_box.origin.y;
  grect_standardize(&clipped);
  grect_clip(&clipped, &bitmap->bounds);
  grect_clip(&clipped, &ctx->draw_state.clip_box);
  if (grect_is_empty(&clipped)) {
    return;
  }

  for (int16_t y = clipped.origin.y; y < clipped.origin.y + clipped.size.h; ++y) {
    const GBitmapDataRowInfo row = gbitmap_get_data_row_info(bitmap, (uint16_t)y);
    const int16_t x1 = MAX(clipped.origin.x, row.min_x);
    const int16_t x2 = MIN(clipped.origin.x + clipped.size.w - 1, row.max_x);
    if (x2 >= x1) {
      memset(row.data + x1, fill_color.argb, (size_t)(x2 - x1 + 1));
    }
  }
}

//! Only graphics_line.c's zero-length stroked-line case reaches this, and that
//! needs stroke_width > 1. The watchface draws every line at width 1, so
//! rather than vendor graphics_circle.c and its s_circle_table this aborts: if
//! it ever fires, the render would have been wrong and I want to know.
void graphics_fill_circle(GContext *ctx, GPoint p, uint16_t radius) {
  (void)ctx; (void)p; (void)radius;
  WTF;
}
