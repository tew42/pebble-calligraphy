/* sin_lookup / cos_lookup for the host build.
 *
 * The firmware's are table lookups whose implementation is not in the
 * open-source tree -- they live in coredevices/pebbleos-nonfree, which the
 * README states is not under the Apache-2.0 licence covering the rest of the
 * firmware, so it is deliberately not vendored here. Both are specified to
 * return a value scaled to TRIG_MAX_RATIO (0xffff), so any table and this
 * computation must agree to within a few least-significant bits of that scale.
 *
 * This is the harness's one substantive deviation from the firmware. Rather
 * than assert it is harmless, check_raster.py compiles this with
 * -DTRIG_LSB_SHIFT=8 -- a perturbation far larger than any plausible table
 * error -- and confirms that not one pixel changes across all 720 minutes.
 */
#include <math.h>
#include <stdint.h>

#include "pbl/util/trig.h"

#ifndef TRIG_LSB_SHIFT
#define TRIG_LSB_SHIFT 0
#endif

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

int32_t sin_lookup(int32_t angle) {
  return (int32_t)(sin((double)angle * 2.0 * M_PI / TRIG_MAX_ANGLE)
                   * TRIG_MAX_RATIO) + TRIG_LSB_SHIFT;
}

int32_t cos_lookup(int32_t angle) {
  return (int32_t)(cos((double)angle * 2.0 * M_PI / TRIG_MAX_ANGLE)
                   * TRIG_MAX_RATIO) - TRIG_LSB_SHIFT;
}
