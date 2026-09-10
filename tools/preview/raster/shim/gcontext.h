/* Stand-in for the firmware's gcontext.h.
 *
 * Upstream's version cannot be vendored: it includes text_layout_private.h and
 * text_resources.h, which drag in font caching, resource loading and PNG
 * decoding. The rasterizer itself never touches any of that, so this declares
 * only the parts of GContext the vendored .c files actually reach.
 *
 * Field names and semantics follow upstream exactly; text_draw_state and
 * font_cache are simply absent. GDrawState and GDrawRawImplementation are NOT
 * redeclared here -- they live in the vendored gtypes.h. */
#pragma once

#include "gtypes.h"

typedef struct GContext {
  GBitmap dest_bitmap;

  /* Always NULL here: the destination is a plain host buffer, not a slice of a
   * live framebuffer, so there is no parent to offset against. */
  void *parent_framebuffer;
  uint8_t parent_framebuffer_vertical_offset;

  GDrawState draw_state;

  /* Set while the framebuffer is captured; every public draw entry point
   * returns early when it is true, exactly as upstream does. */
  bool lock;
} GContext;

/* --- context lifecycle (shim.c) ----------------------------------------- */

//! Point a context at a host buffer of DISP_COLS x DISP_ROWS GColor8 bytes and
//! reset draw_state to the firmware's post-init defaults.
void graphics_context_init(GContext *ctx, uint8_t *framebuffer);

GBitmap *graphics_context_get_bitmap(GContext *ctx);
GBitmap *graphics_capture_frame_buffer(GContext *ctx);
void graphics_release_frame_buffer(GContext *ctx, GBitmap *bitmap);
void graphics_context_mark_dirty_rect(GContext *ctx, GRect rect);

/* --- draw state (shim.c) ------------------------------------------------
 * Transcribed from upstream graphics.c; each is a couple of lines. */

void graphics_context_set_stroke_color(GContext *ctx, GColor color);
void graphics_context_set_fill_color(GContext *ctx, GColor color);
void graphics_context_set_text_color(GContext *ctx, GColor color);
void graphics_context_set_tint_color(GContext *ctx, GColor color);
void graphics_context_set_compositing_mode(GContext *ctx, GCompOp mode);
void graphics_context_set_stroke_width(GContext *ctx, uint8_t stroke_width);
void graphics_context_set_antialiased(GContext *ctx, bool enable);
bool graphics_context_get_antialiased(GContext *ctx);
