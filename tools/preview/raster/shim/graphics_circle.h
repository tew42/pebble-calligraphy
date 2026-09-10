#pragma once
#include "gtypes.h"
/* Reached only by graphics_line.c's zero-length stroked-line case, which needs
 * stroke_width > 1. The watchface never draws that, so rather than vendor
 * graphics_circle.c (and its s_circle_table) this aborts: a silent wrong
 * answer would be worse than a crash that names itself. */
void graphics_fill_circle(GContext *ctx, GPoint p, uint16_t radius);
