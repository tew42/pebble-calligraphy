#pragma once
#include "gtypes.h"
void bitblt_bitmap_into_bitmap(GBitmap *dest, const GBitmap *src, GPoint dest_offset,
                               GCompOp compose_mode, GColor tint_color);
