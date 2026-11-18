#!/usr/bin/env python3
"""Width-profile studies, drawn by the firmware's own rasterizer.

    python3 tools/preview/sheet_profiles.py [kink|price|track2|track3|quadratic|exponent|all]
    ./shot.sh profiles-track2-control-face ...

Everything is rendered through `raster.render_polygons`, so a profile built in
Python is drawn by exactly the pipeline that draws the shipped one --
`check_raster.py` check 10 asserts that, and `profiles.check()` asserts the
shipped profile reproduces the compiled C to 1.4e-6 px over all 720 minutes.

  kink    track 1: what to do where the centerline folds back near overlap
  price   what removing the thinning costs over the whole clock
  track2  symmetric / monotonic profiles, on a no-thinning baseline
  track3  asymmetric / non-monotonic profiles, same baseline
  quadratic  the quadratic taper at other hand lengths and hour thicknesses
  exponent   the quadratic's exponent swept, and asymmetric variants of it
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profiles
import raster
import sheet_workshop as W
import svgcanvas as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
CENTRE = (100.0, 114.0)

#: The shipped waist term saturates at delta 3.80, so it acts only below that.
#: These walk the acting band in even steps -- the clock does reach 0.5, 1.0,
#: 1.5, 2.0, 2.5 and 3.5 degrees, just not within a single hour -- plus two
#: controls past saturation, the second at the sharpest curvature of all.
#:
#: Caveat worth stating: because these are different hours, the stroke points a
#: different way in each column, so separation and orientation vary together.
#: That does not change the profile decision (curvature depends on delta and the
#: stem geometry, not heading) but it does change rasterization, since the 1 px
#: outline skips antialiasing at horizontal, vertical and exactly 45 degrees.
#: Nothing finer than 0.5 degrees exists: the face updates once a minute.
KINK_TIMES = ((12, 0), (9, 49), (7, 38), (6, 33), (8, 44),
              (10, 55), (8, 43), (9, 50), (12, 2))


#: Judge a profile as a watchface: separations spread over the shape space,
#: ending on exact opposition.
NORMAL_TIMES = ((1, 13), (3, 0), (10, 10), (8, 20), (12, 33), (6, 0))

#: Judge whether the pivot reads broad as the hands close. A subset of
#: KINK_TIMES: with the waist held open nothing varies inside the old acting
#: band any more, so its 0.5-degree steps have nothing left to resolve.
CLOSING_TIMES = ((12, 0), (7, 38), (10, 55), (9, 50), (12, 2))

#: The column whose width profile is plotted beside each row.
PLOT_TIME = (10, 10)


def build(times, variants):
    """Render every (variant, time) cell and return frames plus diagnostics."""
    base = raster.gather(times=list(times))
    dense = raster.gather(times=list(times), overrides=profiles.DENSE)
    rows = []
    for label, fn in variants:
        specs, widths = [], []
        for frame, dframe in zip(base, dense):
            ctx = profiles.context_from(
                frame, profiles.separation_degrees(frame["hour"], frame["minute"]))
            w = fn(ctx, dframe)
            widths.append(w)
            poly = profiles.to_polygon_widths(w)
            points = [(x, y) for x, y, *_ in frame["centerline"]]
            specs.append((W.polygon_from(points, poly, W.bisector_tangents(points)),
                          [(x, y) for x, y, *_ in frame["centerline"][frame["pivot"]:]]))
        rows.append((label, raster.render_polygons(specs), widths))
    return base, rows


def overshoot(frame_buffer, centre_points, widths, width, height):
    """Worst distance any lit pixel sits beyond the half-width it was given.

    A jag at the fold shows up as ink further from the centerline than the
    profile asked for, so this measures the thing being judged rather than a
    proxy for it.
    """
    levels = raster.LEVELS
    worst = 0.0
    for y in range(height):
        row = frame_buffer[y * width:(y + 1) * width]
        for x, byte in enumerate(row):
            if not levels[byte]:
                continue
            best = min(range(len(centre_points)),
                       key=lambda i: (centre_points[i][0] - x) ** 2
                                     + (centre_points[i][1] - y) ** 2)
            d = math.hypot(centre_points[best][0] - x, centre_points[best][1] - y)
            worst = max(worst, d - widths[best] * 0.5)
    return worst


def sheet(path, title, notes, times, variants, zoom=5.0, size=170,
          rows=None, base=None):
    if base is None:
        base, rows = build(times, variants)
    label_w, gap, top = 300, 10, 104 + 15 * len(notes)
    cell_h = 228 if zoom <= 1.0 else size
    canvas = S.Canvas(label_w + len(times) * (size + gap) + 20,
                      top + len(rows) * (cell_h + gap) + 24, background=S.PAGE)
    canvas.text(24, 34, title, size=17, fill=S.LABEL, weight="600")
    for i, line in enumerate(notes):
        canvas.text(24, 56 + 15 * i, line, size=10, fill=S.DIM)

    for col, frame in enumerate(base):
        d = profiles.separation_degrees(frame["hour"], frame["minute"])
        canvas.text(label_w + col * (size + gap) + size / 2, top - 10,
                    f"{frame['hour'] % 12 or 12:02d}:{frame['minute']:02d}  "
                    f"d={d:.1f}", size=9, fill=S.LABEL, anchor="middle",
                    weight="600")

    shipped_bufs = None
    for r, (label, frames, widths) in enumerate(rows):
        y = top + r * (cell_h + gap)
        canvas.text(24, y + 16, label, size=10, fill=S.LABEL, weight="600")
        if shipped_bufs is None:
            shipped_bufs = [f["buffer"] for f in frames]
            canvas.text(24, y + 31, "(baseline for the deltas below)", size=8,
                        fill=S.DIM)
        else:
            moved = sum(sum(1 for p, q in zip(a["buffer"], b) if p != q)
                        for a, b in zip(frames, shipped_bufs))
            dw = max(max(abs(a - b) for a, b in zip(w, sw))
                     for w, sw in zip(widths, rows[0][2]))
            canvas.text(24, y + 31, f"pixels changed: {moved}", size=8,
                        fill=S.DIM if moved == 0 else "#f4d35e")
            canvas.text(24, y + 44, f"max width delta: {dw:.2f} px", size=8,
                        fill=S.DIM if dw < 0.3 else "#f4d35e")
        for col, (frame, cframe) in enumerate(zip(frames, base)):
            ox = label_w + col * (size + gap)
            W.panel(canvas, ox, y, size, cell_h, cframe, 0, zoom, frame["buffer"])
            canvas.text(ox + 4, y + cell_h - 4,
                        f"pivot w {widths[col][cframe['pivot']]:.2f}",
                        size=7, fill=S.DIM)
    os.makedirs(OUT, exist_ok=True)
    canvas.write(path)
    print("wrote", path)
    return rows


# --- pricing over the whole clock -------------------------------------------

CLOCK = [(h, m) for h in range(12) for m in range(60)]
_clock_frames = (None, None)


def clock_frames(overrides=None):
    """Every minute of the clock from main.c, optionally with constants changed.

    Only the last configuration is kept: a clock of framebuffers is 33 MB.
    """
    global _clock_frames
    key = tuple(sorted((overrides or {}).items()))
    if _clock_frames[0] != key:
        _clock_frames = (key, raster.gather(times=CLOCK, overrides=overrides))
    return _clock_frames[1]


def render_clock(fn, overrides=None, widths=profiles.SHIPPED_WIDTHS):
    """Every minute of the clock under one profile, as framebuffers."""
    specs = []
    for frame in clock_frames(overrides):
        ctx = profiles.context_from(
            frame, profiles.separation_degrees(frame["hour"], frame["minute"]),
            widths)
        points = [(x, y) for x, y, *_ in frame["centerline"]]
        specs.append((W.polygon_from(points, profiles.to_polygon_widths(fn(ctx)),
                                     W.bisector_tangents(points)),
                      points[frame["pivot"]:]))
    return [frame["buffer"] for frame in raster.render_polygons(specs)]


def price(buffers, against):
    """Differing pixels over the clock, split by what kind of difference.

    A bare total hides the character of a change: ink appearing or vanishing is
    a shape change, a one-level grey shift is rounding noise, and the two can
    sum to the same number.
    """
    levels = raster.LEVELS
    out = dict(frames=0, appear=0, vanish=0, one=0, multi=0, worst=0,
               worst_at=None)
    for (hour, minute), a, b in zip(CLOCK, buffers, against):
        if a == b:
            continue
        out["frames"] += 1
        here = 0
        for p, q in zip(a, b):
            if p == q:
                continue
            here += 1
            mine, theirs = levels[p], levels[q]
            if theirs == 0:
                out["appear"] += 1
            elif mine == 0:
                out["vanish"] += 1
            elif abs(mine - theirs) == 1:
                out["one"] += 1
            else:
                out["multi"] += 1
        if here > out["worst"]:
            out["worst"], out["worst_at"] = here, (hour, minute)
    out["total"] = out["appear"] + out["vanish"] + out["one"] + out["multi"]
    return out


def describe(cost):
    if not cost["total"]:
        return "identical on all 720 minutes"
    hour, minute = cost["worst_at"]
    return (f"{cost['total']} px over {cost['frames']}/720 frames "
            f"({cost['total'] / 720.0:.1f}/frame; worst {cost['worst']} at "
            f"{hour % 12 or 12:02d}:{minute:02d}) -- appear {cost['appear']}, "
            f"vanish {cost['vanish']}, one level {cost['one']}, "
            f"two or more {cost['multi']}")


def price_thinning() -> int:
    """What the waist term is worth, over the clock rather than nine columns."""
    as_drawn = render_clock(profiles.reference)
    identical = sum(a == f["buffer"] for a, f in zip(as_drawn, clock_frames()))
    print(f"control: python `reference` vs the compiled C: {identical}/720 identical")
    open_waist = render_clock(profiles.no_thinning)
    print("waist held open, pressure left on, vs shipped:")
    print("  " + describe(price(open_waist, as_drawn)))
    bare = render_clock(profiles.baseline)
    print("waist held open AND pressure off (the track 2/3 baseline), vs shipped:")
    print("  " + describe(price(bare, as_drawn)))
    print("pressure alone (baseline vs waist-open-with-pressure):")
    print("  " + describe(price(bare, open_waist)))
    touched = [(h, m) for (h, m), a, b in zip(CLOCK, open_waist, as_drawn) if a != b]
    seps = sorted({round(profiles.separation_degrees(h, m), 1) for h, m in touched})
    print(f"separations of the frames the waist term touches: {seps}")
    return 0


# --- the track sheets -------------------------------------------------------

def fill_arc(arc, widths):
    """Fraction of the arc over which the filled polygon is at least 1 px wide.

    Below that gpath drops the span outright, so past this point the stroke is
    the outline and the minute core and the profile no longer reaches the fill.
    """
    threshold = 1.0 + profiles.K["OUTLINE_WIDTH_COMPENSATION"]
    covered = 0.0
    for i in range(1, len(arc)):
        a, b = widths[i - 1], widths[i]
        length = arc[i] - arc[i - 1]
        if a >= threshold and b >= threshold:
            covered += length
        elif a >= threshold or b >= threshold:
            covered += length * abs((max(a, b) - threshold) / (b - a))
    return covered / arc[-1] if arc[-1] else 0.0


def plot(canvas, x, y, w, h, arc, pivot, widths, under=None, top=6.5,
         ticks=(2, 4, 6)):
    """A row's width profile at one time: requested stroke width against arc."""
    canvas.rect(x, y, w, h, fill="#0b0d10", stroke="#242a31", stroke_width=0.6)

    def at(a, v):
        return (x + w * a / arc[-1], y + h - h * min(v, top) / top)
    # below this the filled polygon is under 1 px and gpath draws nothing
    fx, fy = at(0.0, 2.0)
    canvas.line(x, fy, x + w, fy, stroke=S.GUIDE, stroke_width=0.6, dash="3,3")
    px, _ = at(arc[pivot], 0.0)
    canvas.line(px, y, px, y + h, stroke=S.PIVOT, stroke_width=0.6, opacity=0.7)
    if under is not None:
        canvas.polyline([at(a, v) for a, v in zip(arc, under)],
                        stroke=S.REFERENCE, stroke_width=1.0, opacity=0.65)
    canvas.polyline([at(a, v) for a, v in zip(arc, widths)], stroke=S.INK,
                    stroke_width=1.3)
    for value in ticks:
        canvas.text(x + w + 3, at(0.0, value)[1] + 2.5, str(value), size=6.5,
                    fill=S.DIM)


def track_sheets(stem, title, notes, variants, baseline_row=1):
    """One render pass, two sheets: the whole face at 1:1 and the pivot at 4x.

    Row `baseline_row` is the family baseline every other row is priced
    against, over all 720 minutes. Row 0 is the watchface as drawn today, kept
    for the eye; it is priced against the baseline like any other row.
    """
    times = NORMAL_TIMES + CLOSING_TIMES
    base, rows = build(times, variants)
    plot_col = times.index(PLOT_TIME)
    plot_arc = [row[4] for row in base[plot_col]["centerline"]]
    plot_pivot = base[plot_col]["pivot"]

    clock = [render_clock(fn) for _, fn in variants]
    costs = [None if r == baseline_row else price(clock[r], clock[baseline_row])
             for r in range(len(variants))]
    base_widths = rows[baseline_row][2]

    for suffix, zoom, size, what in (
            ("face", 1.0, 200, "Each cell is the whole 200x228 emery framebuffer "
             "at actual size."),
            ("zoom", 5.0, 170, "Each cell is the 42 px around the watch centre at "
             "4x; one square is one device pixel.")):
        label_w, gap, group_gap = 320, 10, 26
        lines = notes + [what]
        top = 118 + 15 * len(lines)
        cell_h = 228 if zoom <= 1.0 else size

        def column_x(col):
            return (label_w + col * (size + gap)
                    + (group_gap if col >= len(NORMAL_TIMES) else 0))
        canvas = S.Canvas(column_x(len(times)) + 20,
                          top + len(rows) * (cell_h + gap) + 24, background=S.PAGE)
        canvas.text(24, 34, f"{title} -- {suffix}", size=17, fill=S.LABEL,
                    weight="600")
        for i, line in enumerate(lines):
            canvas.text(24, 56 + 15 * i, line, size=10, fill=S.DIM)
        canvas.text(column_x(0), top - 28, "AS A WATCHFACE", size=9, fill=S.DIM,
                    weight="600")
        canvas.text(column_x(len(NORMAL_TIMES)), top - 28,
                    "HANDS CLOSING -- does the pivot read broad?", size=9,
                    fill=S.DIM, weight="600")
        for col, frame in enumerate(base):
            d = profiles.separation_degrees(frame["hour"], frame["minute"])
            canvas.text(column_x(col) + size / 2, top - 10,
                        f"{frame['hour'] % 12 or 12:02d}:{frame['minute']:02d}  "
                        f"d={d:.1f}", size=9, fill=S.LABEL, anchor="middle",
                        weight="600")

        for r, (label, frames, widths) in enumerate(rows):
            y = top + r * (cell_h + gap)
            canvas.text(24, y + 14, label, size=10, fill=S.LABEL, weight="600")
            share = fill_arc(plot_arc, widths[plot_col])
            if r == baseline_row:
                canvas.text(24, y + 28, "family baseline: no thinning, no pressure",
                            size=8, fill=S.DIM)
            else:
                cost = costs[r]
                dw = max(max(abs(a - b) for a, b in zip(w, bw))
                         for w, bw in zip(widths, base_widths))
                loud = "#f4d35e"
                canvas.text(24, y + 28,
                            f"vs baseline, 720 min: {cost['total'] / 720.0:.1f} "
                            f"px/frame, {cost['frames']} frames", size=8,
                            fill=loud if cost["total"] else S.DIM)
                canvas.text(24, y + 40,
                            f"appear {cost['appear']}  vanish {cost['vanish']}  "
                            f"1-level {cost['one']}  2+ {cost['multi']}", size=8,
                            fill=S.DIM)
                canvas.text(24, y + 52, f"max width delta {dw:.2f} px", size=8,
                            fill=loud if dw >= 0.3 else S.DIM)
            canvas.text(24, y + 64,
                        f"fill carries {100.0 * share:.0f}% of the arc at "
                        f"{PLOT_TIME[0]}:{PLOT_TIME[1]:02d}", size=8, fill=S.DIM)
            plot(canvas, 24, y + 72, 262, 84, plot_arc, plot_pivot,
                 widths[plot_col],
                 None if r == baseline_row else base_widths[plot_col])
            for col, (frame, cframe) in enumerate(zip(frames, base)):
                ox = column_x(col)
                W.panel(canvas, ox, y, size, cell_h, cframe, 0, zoom,
                        frame["buffer"])
                canvas.text(ox + 4, y + cell_h - 4,
                            f"pivot w {widths[col][cframe['pivot']]:.2f}",
                            size=7, fill=S.DIM)
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, f"{stem}-{suffix}.svg")
        canvas.write(path)
        print("wrote", path)

    for (label, _), cost in zip(variants, costs):
        print(f"  {label:42s} "
              + ("(baseline)" if cost is None else describe(cost)))
    return rows, costs


COMMON_NOTES = [
    "Baseline for every delta: the shipped two-smoothstep profile with the "
    "near-overlap thinning removed and the pressure multiplier off.",
    "Left of each row: requested stroke width against arc at 10:10 (white), the "
    "baseline in orange, the pivot in blue. Under the dashed line the filled "
    "polygon is below 1 px and only the outline and core draw.",
    "Only ~10 distinct widths survive vertex rounding, so rows within ~0.3 px of "
    "each other are the same drawing. Closing columns are different hours, so "
    "heading varies with separation.",
]


def track2() -> int:
    track_sheets(
        "profiles-track2-control",
        "Track 2a. The value at the pivot, and whether it is needed at all",
        ["Monotonic profiles from the swell's peak (6 px) to the minute point "
         "(1 px). What varies: the control value at the pivot, and where it sits."]
        + COMMON_NOTES, profiles.TRACK2_CONTROL)
    track_sheets(
        "profiles-track2-shape",
        "Track 2b. Shapes with no control value",
        ["Monotonic profiles from the swell's peak (6 px) to the minute point "
         "(1 px), none of which knows where the pivot is."]
        + COMMON_NOTES, profiles.TRACK2_SHAPE)
    return 0


def track3() -> int:
    track_sheets(
        "profiles-track3",
        "Track 3. Asymmetric and non-monotonic profiles",
        ["The baseline plus a feature tied to the pivot: pressure, a bulge out "
         "of the turn, a pinch into it, or a different fall either side."]
        + COMMON_NOTES, profiles.TRACK3)
    return 0


# --- the quadratic taper away from the shipped geometry ---------------------

@dataclass(frozen=True)
class Setting:
    """main.c with its hand lengths and hour thickness changed."""
    hour: float = 0.60
    minute: float = 0.90
    body: float = 6.0
    note: str = ""

    @property
    def widths(self):
        return profiles.Widths.for_body(self.body)

    @property
    def overrides(self):
        return {**self.widths.overrides(),
                "HOUR_LENGTH_RATIO": f"{self.hour!r}f",
                "MINUTE_LENGTH_RATIO": f"{self.minute!r}f"}

    @property
    def label(self):
        return (f"hands {self.hour:.2f} / {self.minute:.2f}, body "
                f"{self.body:g} px" + (f" -- {self.note}" if self.note else ""))


#: Inner radii r = L(1 - stem) stay within the 3/5 <= r_m/r_h <= 5/3 budget of
#: section 34 for every one of these: 1.20, 1.44, 1.03, 1.00, 1.20, 1.38.
LENGTH_SETTINGS = (
    Setting(note="shipped"),
    Setting(hour=0.50, note="short hour hand"),
    Setting(hour=0.70, note="long hour hand"),
    Setting(minute=0.75, note="short minute hand"),
    Setting(hour=0.50, minute=0.75, note="both smaller"),
    Setting(hour=0.55, minute=0.95, note="most contrast"),
)

THICKNESS_SETTINGS = (
    Setting(body=4.0),
    Setting(body=6.0, note="shipped"),
    Setting(body=8.0),
    Setting(body=10.0),
    Setting(body=12.0, note="the 2x ceiling"),
)

CORNER_SETTINGS = (
    Setting(hour=0.50, body=12.0, note="thick, short hour"),
    Setting(hour=0.70, body=12.0, note="thick, long hour"),
    Setting(minute=0.75, body=4.0, note="thin, short minute"),
    Setting(hour=0.55, minute=0.95, body=12.0, note="thick, most contrast"),
)


def measure(setting):
    """One setting over the whole clock: the control, then both profiles."""
    overrides, widths = setting.overrides, setting.widths
    frames = clock_frames(overrides)
    as_drawn = render_clock(profiles.reference, overrides, widths)
    identical = sum(a == f["buffer"] for a, f in zip(as_drawn, frames))
    if identical != len(frames):
        raise SystemExit(f"{setting.label}: python reproduces the C on only "
                         f"{identical}/720 minutes; not drawing it")
    control = render_clock(profiles.baseline, overrides, widths)
    quadratic = render_clock(profiles.quadratic, overrides, widths)

    place, at_pivot = [], []
    for frame in frames:
        ctx = profiles.context_from(
            frame, profiles.separation_degrees(frame["hour"], frame["minute"]),
            widths)
        place.append(profiles.domain(ctx)[2])
        at_pivot.append(profiles.quadratic(ctx)[ctx.pivot])

    def cells(fn, buffers):
        out = []
        for hour, minute in NORMAL_TIMES + CLOSING_TIMES:
            index = (hour % 12) * 60 + minute
            frame = frames[index]
            ctx = profiles.context_from(
                frame, profiles.separation_degrees(hour, minute), widths)
            out.append(dict(frame={k: v for k, v in frame.items() if k != "buffer"},
                            buffer=buffers[index], widths=fn(ctx)))
        return out
    return dict(setting=setting, cost=price(quadratic, control),
                place=(min(place), max(place)),
                at_pivot=(min(at_pivot), max(at_pivot)),
                control=cells(profiles.baseline, control),
                quadratic=cells(profiles.quadratic, quadratic))


def setting_sheets(stem, title, notes, settings, pair=True):
    """The quadratic at each setting, beside the control-value profile it
    would replace (pair=True), as a whole-face sheet and a 4x crop."""
    measured = [measure(setting) for setting in settings]
    times = NORMAL_TIMES + CLOSING_TIMES
    plot_col = times.index(PLOT_TIME)
    loud = "#f4d35e"

    rows = []
    for m in measured:
        if pair:
            rows.append((m, "control", True))
        rows.append((m, "quadratic", not pair))

    for suffix, zoom, size, what in (
            ("face", 1.0, 200, "Each cell is the whole 200x228 emery framebuffer "
             "at actual size."),
            ("zoom", 5.0, 170, "Each cell is the 42 px around the watch centre at "
             "4x; one square is one device pixel.")):
        label_w, gap, group_gap, pair_gap = 380, 10, 26, 16
        lines = notes + [what]
        top = 118 + 15 * len(lines)
        cell_h = 228 if zoom <= 1.0 else size

        def column_x(col):
            return (label_w + col * (size + gap)
                    + (group_gap if col >= len(NORMAL_TIMES) else 0))
        ys, y = [], top
        for m, kind, first in rows:
            if first and ys:
                y += pair_gap
            ys.append(y)
            y += cell_h + gap
        canvas = S.Canvas(column_x(len(times)) + 20, y + 24, background=S.PAGE)
        canvas.text(24, 34, f"{title} -- {suffix}", size=17, fill=S.LABEL,
                    weight="600")
        for i, line in enumerate(lines):
            canvas.text(24, 56 + 15 * i, line, size=10, fill=S.DIM)
        canvas.text(column_x(0), top - 28, "AS A WATCHFACE", size=9, fill=S.DIM,
                    weight="600")
        canvas.text(column_x(len(NORMAL_TIMES)), top - 28,
                    "HANDS CLOSING -- does the pivot read broad?", size=9,
                    fill=S.DIM, weight="600")
        for col, (hour, minute) in enumerate(times):
            d = profiles.separation_degrees(hour, minute)
            canvas.text(column_x(col) + size / 2, top - 10,
                        f"{hour % 12 or 12:02d}:{minute:02d}  d={d:.1f}", size=9,
                        fill=S.LABEL, anchor="middle", weight="600")

        for (m, kind, first), y in zip(rows, ys):
            setting, k = m["setting"], m["setting"].widths
            cells = m[kind]
            arc = [row[4] for row in cells[plot_col]["frame"]["centerline"]]
            pivot = cells[plot_col]["frame"]["pivot"]
            share = fill_arc(arc, cells[plot_col]["widths"])
            text_y = y + 14
            if first:
                canvas.text(24, text_y, setting.label, size=10, fill=S.LABEL,
                            weight="600")
                text_y += 13
            if kind == "control":
                canvas.text(24, text_y, f"two smoothsteps through {k.mid:g} px "
                            f"at the pivot", size=8.5, fill=S.LABEL)
                canvas.text(24, text_y + 12,
                            f"pivot at {m['place'][0]:.2f}-{m['place'][1]:.2f} of "
                            f"the arc, over the clock", size=8, fill=S.DIM)
                text_y += 24
            else:
                lo, hi = m["at_pivot"]
                off = max(abs(lo - k.mid), abs(hi - k.mid))
                cost = m["cost"]
                canvas.text(24, text_y, "quadratic taper, no control value",
                            size=8.5, fill=S.LABEL)
                canvas.text(24, text_y + 12,
                            f"at the pivot: {lo:.2f}-{hi:.2f} px  "
                            f"(control value {k.mid:g})", size=8,
                            fill=loud if off >= 0.3 else S.DIM)
                canvas.text(24, text_y + 24,
                            f"vs control, 720 min: {cost['total'] / 720.0:.1f} "
                            f"px/frame  (+{cost['appear']} -{cost['vanish']} "
                            f"grey {cost['one'] + cost['multi']})", size=8,
                            fill=S.DIM)
                text_y += 36
            canvas.text(24, text_y,
                        f"fill carries {100.0 * share:.0f}% of the arc at "
                        f"{PLOT_TIME[0]}:{PLOT_TIME[1]:02d}", size=8, fill=S.DIM)
            scale_top = max(6.5, k.peak + 0.5)
            ticks = (2, 4, 6) if scale_top <= 6.5 else (4, 8, 12)
            plot(canvas, 24, y + 78, 262, cell_h - 86 if zoom > 1.0 else 84,
                 arc, pivot, cells[plot_col]["widths"],
                 m["control"][plot_col]["widths"] if kind == "quadratic" else None,
                 top=scale_top, ticks=tuple(t for t in ticks if t < scale_top))
            for col, cell in enumerate(cells):
                ox = column_x(col)
                W.panel(canvas, ox, y, size, cell_h, cell["frame"], 0, zoom,
                        cell["buffer"])
                canvas.text(ox + 4, y + cell_h - 4,
                            f"pivot w {cell['widths'][cell['frame']['pivot']]:.2f}",
                            size=7, fill=S.DIM)
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, f"{stem}-{suffix}.svg")
        canvas.write(path)
        print("wrote", path)

    for m in measured:
        k = m["setting"].widths
        print(f"  {m['setting'].label:52s} pivot at {m['place'][0]:.3f}-"
              f"{m['place'][1]:.3f}; quadratic there {m['at_pivot'][0]:.2f}-"
              f"{m['at_pivot'][1]:.2f} vs {k.mid:g}; " + describe(m["cost"]))
    return measured


QUADRATIC_NOTES = [
    "Every setting is main.c compiled with those constants; the Python profile "
    "is checked pixel-identical to it on all 720 minutes before anything is drawn.",
    "Thinning and pressure are off. The hour end scales with the body: tip = "
    "body / 2, and the widening takes 5% of the hour side per 6 px of body.",
    "Left of each row: requested stroke width against arc at 10:10 (white), the "
    "control-value profile in orange, the pivot in blue. Under the dashed line "
    "only the outline and core draw.",
]


def quadratic() -> int:
    setting_sheets(
        "profiles-quadratic-lengths",
        "Quadratic taper across hand lengths",
        ["w = tip + (peak - tip)(1 - u)^2 has no control value, so what it puts "
         "at the pivot depends on where the pivot falls in the arc. Hour body "
         "6 px throughout."] + QUADRATIC_NOTES, LENGTH_SETTINGS)
    setting_sheets(
        "profiles-quadratic-thickness",
        "Quadratic taper across hour thickness",
        ["w = tip + (peak - tip)(1 - u)^2 has no control value, so what it puts "
         "at the pivot scales with the peak. Hands 0.60 / 0.90 throughout."]
        + QUADRATIC_NOTES, THICKNESS_SETTINGS)
    setting_sheets(
        "profiles-quadratic-corners",
        "Quadratic taper, lengths and thickness together",
        ["The quadratic alone, where the two changes compound."]
        + QUADRATIC_NOTES, CORNER_SETTINGS, pair=False)
    return 0


EXPONENT_NOTES = [
    "Baseline for every delta: the quadratic taper, w = tip + (peak - tip)(1 - u)^p "
    "with p = 2, thinning and pressure off.",
    "Left of each row: requested stroke width against arc at 10:10 (white), the "
    "quadratic in orange, the pivot in blue. Under the dashed line the filled "
    "polygon is below 1 px and only the outline and core draw.",
    "Only ~10 distinct widths survive vertex rounding, so rows within ~0.3 px of "
    "each other are the same drawing. Closing columns are different hours, so "
    "heading varies with separation.",
]


def exponent() -> int:
    track_sheets(
        "profiles-exponent",
        "The quadratic's exponent: how quickly the pen lifts",
        ["w = tip + (peak - tip)(1 - u)^p from the end of the hour swell (u = 0) "
         "to the minute point (u = 1). Shipped geometry, 6 px body."]
        + EXPONENT_NOTES, profiles.EXPONENT)
    track_sheets(
        "profiles-asymmetric",
        "Asymmetric variants of the quadratic",
        ["Skew: w = tip + (peak - tip)(1 - u^a)^2, never looking at the pivot. "
         "Pivot split: a different fall either side, meeting at the quadratic's "
         "own pivot width."] + EXPONENT_NOTES, profiles.ASYMMETRIC)
    return 0


def kink() -> int:
    notes = [
        "Near overlap the centerline folds back on itself. At exact overlap it is a true "
        "reversal: the path runs in along a ray and back out along the same ray.",
        "The shipped rule thins the waist by hand SEPARATION. The curvature rule thins by the "
        "local radius instead, holding w <= 2R -- the condition for the inner offset not to cusp.",
        "Measured: the sharpest point is NOT at exact overlap (where the fold is a clean "
        "reversal) but just after it, and it sits between samples, so it is taken per arc interval.",
    ]
    # Rendered once, drawn twice: the face at 1:1 to judge it as a watchface,
    # the 5x crop to see what the fold is actually doing.
    base, rows = build(KINK_TIMES, profiles.TRACK1)
    sheet(os.path.join(OUT, "profiles-kink-face.svg"),
          "Track 1. What to do where the stroke folds -- full face, 1:1",
          notes + ["Each cell is the whole 200x228 emery framebuffer at actual "
                   "size. The companion -zoom sheet is the same grid at 5x."],
          KINK_TIMES, profiles.TRACK1, zoom=1.0, size=200,
          rows=rows, base=base)
    sheet(os.path.join(OUT, "profiles-kink-zoom.svg"),
          "Track 1. What to do where the stroke folds -- fold at 5x",
          notes + ["Same grid as the -face sheet, cropped to the centre so the "
                   "fold is legible. Each square is one device pixel."],
          KINK_TIMES, profiles.TRACK1, zoom=5.0, size=170,
          rows=rows, base=base)
    return 0



def main(argv) -> int:
    which = argv[1] if len(argv) > 1 else "all"
    jobs = {"kink": kink, "price": price_thinning, "track2": track2,
            "track3": track3, "quadratic": quadratic, "exponent": exponent}
    if which == "all":
        return max(job() for job in jobs.values())
    if which not in jobs:
        print(__doc__)
        return 2
    return jobs[which]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
