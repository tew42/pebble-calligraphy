/* Build configuration for the host build of the vendored PebbleOS rasterizer.
 * Force-included ahead of every translation unit.
 *
 * The platform description itself is NOT written here -- it comes from the
 * vendored fw/board/display.h, selected by -DCONFIG_BOARD_QEMU_EMERY or
 * -DCONFIG_BOARD_QEMU_GABBRO, which is where PBL_COLOR, PBL_RECT/PBL_ROUND and
 * the display dimensions actually live. That keeps emery at 200x228 rect and
 * gabbro at 260x260 round on the firmware's authority rather than mine, and
 * lets gtypes.h derive the PBL_IF_*_ELSE macros as upstream intends. */
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
/* graphics_private_raw.c calls memset without including string.h -- in the
 * firmware build it arrives transitively. Declared here so the vendored file
 * stays unedited and does not fall back to an implicit int-returning memset. */
#include <string.h>

#if !defined(CONFIG_BOARD_QEMU_EMERY) && !defined(CONFIG_BOARD_QEMU_GABBRO)
#define CONFIG_BOARD_QEMU_EMERY 1
#endif

/* Both supported boards are 8 bits per pixel, one byte of ARGB per pixel.
 * graphics_private_raw.c compiles its blending away entirely unless this is 8,
 * so getting it wrong would silently produce a hard-edged render. */
#define CONFIG_SCREEN_COLOR_DEPTH_BITS 8

#include "board/display.h"
