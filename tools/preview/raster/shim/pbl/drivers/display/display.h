/* Upstream's copy of this path includes gtypes.h back again, so it cannot be
 * vendored without a cycle. Everything gtypes.h needs from it -- the display
 * dimensions and GBitmapDataRowInfoInternal -- comes from the vendored
 * board/display.h. */
#pragma once
#include "board/display.h"
