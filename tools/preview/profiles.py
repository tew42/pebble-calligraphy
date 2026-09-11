#!/usr/bin/env python3
"""Width profiles as data, so the envelope can be explored without editing main.c.

    python3 tools/preview/profiles.py     # verifies `shipped` against the C

The watchface assembles its stroke width from four separate mechanisms -- an
hour-side contraction, a minute-side taper, a waist override near overlap, and a
pressure multiplier over the top. They are all the same thing: one function
w(s) from the hour body to the minute point. This module expresses that function
directly, as a width per centerline sample, so alternatives are values rather
than patches.

`shipped` reproduces `calculate_stroke_width` exactly and is the control: nothing
else here is trustworthy unless it renders pixel-identically to the compiled C.
`check()` asserts that over all 720 minutes.

Two facts from docs/pivot-design.md that bound everything in here:

  * every polygon vertex is rounded to an integer, and across 49 samples only
    ~10 distinct widths survive, so two profiles agreeing to within ~0.3 px at
    the sample points are the *same drawing*;
  * on the minute side the filled polygon is already below 1 px over the outer
    ~46 px of arc, where `gpath` drops the span entirely, so profile detail down
    there reaches the outline and the core but not the fill.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import raster

# --- the constants the profile runs between, read from main.c ---------------

MAIN_C = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "src", "c", "main.c")


def constants():
    """The width-related #defines, so this file cannot drift from the C."""
    import re
    source = open(MAIN_C).read()
    wanted = ("HOUR_TIP_WIDTH", "HOUR_BODY_WIDTH", "MIDDLE_WIDTH",
              "MINUTE_TIP_WIDTH", "MINIMUM_STROKE_WIDTH", "HOUR_SWELL_POSITION",
              "PRESSURE_VARIATION", "OUTLINE_WIDTH_COMPENSATION",
              "VECTOR_EPSILON")
    out = {}
    for name in wanted:
        match = re.search(r"^#define[ \t]+" + name + r"[ \t]+([0-9.]+)f?\s*$",
                          source, re.MULTILINE)
        if not match:
            raise SystemExit(f"could not read #define {name} from main.c")
        out[name] = float(match.group(1))
    return out


K = constants()


# --- the context a profile is evaluated against -----------------------------

@dataclass
class Context:
    """Everything a profile may depend on, for one rendered frame."""
    arc: list          # cumulative arc length at each of the 49 samples
    total: float       # arc[-1]
    pivot: int         # index of the pivot sample
    waist_opening: float   # 0..1, the shipped near-overlap waist term
    separation: float      # degrees between the hands
    points: list           # centerline points, for curvature-aware profiles

    @property
    def pivot_position(self):
        return self.arc[self.pivot] / self.total if self.total else 0.0

    def position(self, index):
        return self.arc[index] / self.total if self.total else 0.0

    @property
    def middle_width(self):
        """What the shipped code calls effective_middle_width."""
        return lerp(K["MINIMUM_STROKE_WIDTH"], K["MIDDLE_WIDTH"],
                    smooth_unit(self.waist_opening))


def context_from(frame, separation):
    # arc length comes from the C's own s_cumulative_length rather than being
    # recomputed from the printed points: the profile is a function of it, so
    # re-deriving it would compare against a slightly different parameter.
    points = [(row[0], row[1]) for row in frame["centerline"]]
    arc = [row[4] for row in frame["centerline"]]
    return Context(arc=arc, total=arc[-1], pivot=frame["pivot"],
                   waist_opening=frame["scale"], separation=separation,
                   points=points)


# --- helpers, matching main.c's own -----------------------------------------

def clamp(value, low, high):
    return low if value < low else high if value > high else value


def lerp(a, b, t):
    return a + (b - a) * t


def smooth_unit(value):
    p = clamp(value, 0.0, 1.0)
    return p * p * (3.0 - 2.0 * p)


# --- the control ------------------------------------------------------------

def shipped(ctx):
    """`calculate_stroke_width` and the pressure bias, transcribed.

    Returns stroke width per sample, before OUTLINE_WIDTH_COMPENSATION.
    """
    widths = []
    pivot_position = ctx.pivot_position
    middle = ctx.middle_width
    for index in range(len(ctx.arc)):
        position = ctx.position(index)
        if position <= pivot_position:
            if pivot_position < K["VECTOR_EPSILON"]:
                width = middle
            else:
                hour = clamp(position / pivot_position, 0.0, 1.0)
                if hour <= K["HOUR_SWELL_POSITION"]:
                    swell = (hour / K["HOUR_SWELL_POSITION"]
                             if K["HOUR_SWELL_POSITION"] > K["VECTOR_EPSILON"]
                             else 1.0)
                    width = lerp(K["HOUR_TIP_WIDTH"], K["HOUR_BODY_WIDTH"],
                                 smooth_unit(swell))
                else:
                    contraction = ((hour - K["HOUR_SWELL_POSITION"])
                                   / (1.0 - K["HOUR_SWELL_POSITION"]))
                    width = lerp(K["HOUR_BODY_WIDTH"], middle,
                                 smooth_unit(contraction))
        else:
            remaining = 1.0 - pivot_position
            if remaining < K["VECTOR_EPSILON"]:
                width = middle
            else:
                minute = clamp((position - pivot_position) / remaining, 0.0, 1.0)
                width = lerp(middle, K["MINUTE_TIP_WIDTH"], smooth_unit(minute))

        envelope = 4.0 * position * (1.0 - position)
        width *= 1.0 + K["PRESSURE_VARIATION"] * envelope * (pivot_position - position)
        widths.append(width)
    return widths


def to_polygon_widths(widths):
    """Apply OUTLINE_WIDTH_COMPENSATION exactly as build_stroke_polygon does."""
    c = K["OUTLINE_WIDTH_COMPENSATION"]
    return [w - c if w - c > 0.0 else 0.0 for w in widths]


# --- verification -----------------------------------------------------------

def separation_degrees(hour, minute):
    d = abs((30.0 * (hour % 12) + 0.5 * minute) - 6.0 * minute) % 360.0
    return min(d, 360.0 - d)


def check(times=None, verbose=True):
    """`shipped` must reproduce the C's own widths, or nothing else here counts."""
    times = times or [(h, m) for h in range(12) for m in range(60)]
    frames = raster.gather(times=times, want_frames=False)
    worst = 0.0
    worst_at = None
    for frame in frames:
        ctx = context_from(frame, separation_degrees(frame["hour"], frame["minute"]))
        mine = to_polygon_widths(shipped(ctx))
        theirs = [row[3] for row in frame["centerline"]]
        for a, b in zip(mine, theirs):
            if abs(a - b) > worst:
                worst = abs(a - b)
                worst_at = (frame["hour"], frame["minute"])
    if verbose:
        print(f"shipped profile vs the compiled C, {len(frames)} frames x "
              f"{len(frames[0]['centerline'])} samples")
        print(f"  worst width disagreement: {worst:.3e} px"
              + (f" at {worst_at[0] % 12 or 12:02d}:{worst_at[1]:02d}"
                 if worst_at else ""))
    return worst


def main() -> int:
    worst = check()
    # float32 in the C against float64 here, over widths of order 6 px
    if worst > 1e-4:
        print("FAIL: the reimplementation does not match the C")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# --- curvature, for the kink track ------------------------------------------

#: A dense reference for curvature. CENTERLINE_POINT_COUNT is hard-capped at
#: 255 by main.c's own #error, since pivot_index is a uint8_t, so this has to
#: stay under it: 16 + 180 + 16 + 1 = 213, giving ~0.5 px in the connector.
DENSE = {"HOUR_STEM_SEGMENTS": "16", "CONNECTOR_SEGMENTS": "180",
         "MINUTE_STEM_SEGMENTS": "16"}


def radius_at_samples(ctx, dense_frame):
    """Radius of curvature at each coarse sample, from a dense reference.

    A three-point circumradius on the 49 shipped samples is meaningless near the
    kink, where the points are 3 px apart and the curve turns inside that. The
    dense frame samples the same curve at ~0.45 px, so the same estimator is
    sound there; it is evaluated at the coarse samples' own arc positions.
    """
    dp = [(row[0], row[1]) for row in dense_frame["centerline"]]
    da = [row[4] for row in dense_frame["centerline"]]

    def radius(i):
        """Arc step over turn angle.

        A circumradius through three points cannot see a reversal: at exact hand
        overlap the centerline runs in along a ray and back out along the same
        ray, so the three points are collinear and the circumradius reads large
        precisely where the curve is sharpest. Turn angle per unit arc does not
        have that blind spot -- a reversal is a turn of pi.
        """
        (ax, ay), (bx, by), (cx, cy) = dp[i - 1], dp[i], dp[i + 1]
        ux, uy = bx - ax, by - ay
        vx, vy = cx - bx, cy - by
        lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
        if lu < 1e-9 or lv < 1e-9:
            return float("inf")
        cross = (ux * vy - uy * vx) / (lu * lv)
        dot = (ux * vx + uy * vy) / (lu * lv)
        turn = abs(math.atan2(cross, dot))
        if turn < 1e-9:
            return float("inf")
        return 0.5 * (lu + lv) / turn

    # Each coarse sample owns the arc interval halfway to its neighbours, and
    # takes the SHARPEST curvature in it. Point-sampling at the sample position
    # is not good enough: at exact overlap the centerline reverses 0.068 px past
    # the pivot, between two samples 3 px apart, so the point value reads
    # R = 94.7 where the true answer is R = 0.003.
    radii = []
    n = len(ctx.arc)
    for i, target in enumerate(ctx.arc):
        lo = target if i == 0 else 0.5 * (ctx.arc[i - 1] + target)
        hi = target if i == n - 1 else 0.5 * (target + ctx.arc[i + 1])
        worst = float("inf")
        for k in range(1, len(dp) - 1):
            if lo - 1e-9 <= da[k] <= hi + 1e-9:
                worst = min(worst, radius(k))
        if worst == float("inf"):
            j = min(range(1, len(dp) - 1), key=lambda k: abs(da[k] - target))
            worst = radius(j)
        radii.append(worst)
    return radii


# --- track 1: what to do at the kink ----------------------------------------

def _base(ctx, waist_opening):
    """The shipped profile with the waist term forced to a given opening."""
    saved = ctx.waist_opening
    ctx.waist_opening = waist_opening
    try:
        return shipped(ctx)
    finally:
        ctx.waist_opening = saved


def no_thinning(ctx, dense=None):
    """The waist never closes: MIDDLE_WIDTH straight through the fold."""
    return _base(ctx, 1.0)


def thinning_band(scale):
    """The shipped rule with its band widened (scale > 1) or narrowed."""
    def profile(ctx, dense=None):
        return _base(ctx, clamp(ctx.waist_opening / scale, 0.0, 1.0))
    profile.__name__ = f"band_x{scale:g}"
    return profile


def thinning_floor(floor):
    """The shipped rule, but the waist bottoms out at `floor` px, not 1 px."""
    def profile(ctx, dense=None):
        t = smooth_unit(ctx.waist_opening)
        middle = lerp(floor, K["MIDDLE_WIDTH"], t)
        saved = ctx.waist_opening
        # solve for the opening that yields this middle through the shipped path
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            ctx.waist_opening = mid
            if ctx.middle_width < middle:
                lo = mid
            else:
                hi = mid
        try:
            return shipped(ctx)
        finally:
            ctx.waist_opening = saved
    profile.__name__ = f"floor{floor:g}"
    return profile


def curvature_capped(ctx, dense=None):
    """No band and no special case: hold w <= 2R everywhere.

    2R is exactly the condition for the inner offset not to cusp, so this is the
    principled version of what the separation term approximates -- and unlike the
    separation term it is a property of the curve rather than of the clock.
    """
    widths = no_thinning(ctx)
    if dense is None:
        return widths
    radii = radius_at_samples(ctx, dense)
    # Floored at MINIMUM_STROKE_WIDTH: at a true reversal R -> 0, so an
    # unfloored 2R would collapse the stroke to nothing at exactly the fold the
    # design wants to keep. The shipped waist term has the same floor.
    floor = K["MINIMUM_STROKE_WIDTH"]
    return [max(floor, min(w, 2.0 * r)) for w, r in zip(widths, radii)]


TRACK1 = (
    ("shipped", lambda ctx, dense=None: shipped(ctx)),
    ("no thinning at all", no_thinning),
    ("band x2 (thins further out)", thinning_band(2.0)),
    ("band x0.5 (thins only very close)", thinning_band(0.5)),
    ("floor 2 px instead of 1", thinning_floor(2.0)),
    ("curvature rule, w <= 2R", curvature_capped),
)
