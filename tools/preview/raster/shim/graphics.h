/* Stand-in for the firmware's graphics.h, which pulls in graphics_bitmap.h and
 * graphics_circle.h. Declares only what the vendored .c files call. */
#pragma once

#include "gcontext.h"
#include "gtypes.h"
#include "graphics_line.h"

//! The firmware's *internal* two-argument form. Not the public SDK call of the
//! same name, which takes a radius and a corner mask. gpath.c's non-antialiased
//! span callback uses this one.
void graphics_fill_rect(GContext *ctx, const GRect *rect);

void graphics_draw_pixel(GContext *ctx, GPoint point);

//! Only reachable from graphics_line.c's zero-length stroked-line case, which
//! needs stroke_width > 1.
void graphics_fill_circle(GContext *ctx, GPoint p, uint16_t radius);

uint8_t gbitmap_get_bits_per_pixel(GBitmapFormat format);
void gbitmap_init_as_sub_bitmap(GBitmap *sub_bitmap, const GBitmap *base_bitmap, GRect sub_rect);
