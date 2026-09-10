#!/usr/bin/env python3
"""Check the raster harness against predictions made from the firmware source.

    python3 tools/preview/check_raster.py

Each expectation here was derived by reading vendor/pebbleos before the harness
could run, and then confirmed by hand-evaluating the integer arithmetic in
Python.  That ordering is the point: if the shim misplaces a pixel, these fail
rather than quietly agreeing with whatever the shim happens to do.

They are also the tripwire for a vendor refresh.  If fetch.sh moves to a newer
upstream and the rasterizer has changed, these stop passing.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import raster
import sheet_envelope
import gifwriter

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK_MAIN = os.path.join(HERE, "raster", "check_main.c")
REFERENCES = os.path.join(HERE, "vendor", "pebbleos", "tests", "test_images")

# Firmware unit-test fixtures: (our fixture name, its committed reference image).
FIXTURES = (
    ("crossing", "gpath_filled_crossing_aa.8bit.png"),
    ("duplicates", "gpath_filled_duplicates_aa.8bit.png"),
    ("single_duplicate", "gpath_filled_single_duplicate_aa.8bit.png"),
    ("house", "gpath_filled_aa.8bit.png"),
    ("bolt", "gpath_filled_bolt_aa.8bit.png"),
)

failures: list[str] = []
notes: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}: {got!r}"
          + ("" if ok else f"  want {want!r}"))
    if not ok:
        failures.append(label)


def raw_run(commands, board="emery"):
    """Compile check_main.c against the vendored rasterizer and run commands."""
    with tempfile.TemporaryDirectory() as directory:
        binary = os.path.join(directory, "check")
        subprocess.run(["gcc", "-std=gnu11", "-O2", "-w", *raster.cflags(board),
                        "-o", binary, CHECK_MAIN, *raster.SOURCES,
                        "-lm"], check=True)
        return subprocess.run([binary], input="\n".join(commands) + "\n",
                              capture_output=True, text=True,
                              check=True).stdout


def geometry(commands, board="emery"):
    """As raw_run, but parsed into (label, digit rows) frames."""
    _, width, height = raster.BOARDS[board]
    out = raw_run(commands, board)
    frames, rows = [], None
    for line in out.splitlines():
        if line.startswith("# "):
            rows = []
            frames.append((line[2:], rows))
        elif rows is not None:
            rows.append(line)
    for _, r in frames:
        assert len(r) == height, f"expected {height} rows, got {len(r)}"
    return frames


def fixture_frames(names):
    """Run the fixture command and return raw framebuffer bytes for each."""
    out = raw_run(["fixture %s 1" % n for n in names])
    blocks, current = [], None
    for line in out.splitlines():
        if line.startswith("#"):
            current = []
            blocks.append(current)
        elif current is not None:
            current.append(line)
    return [bytes(int(r[i * 2:i * 2 + 2], 16)
                  for r in rows for i in range(len(r) // 2))
            for rows in blocks]


def reference_frame(name):
    """A committed reference PNG as framebuffer bytes.

    The framebuffer is one ARGB byte per pixel with two bits per channel; the
    PNG is 8 bits per channel, so each channel is the top two bits and alpha is
    always opaque.
    """
    width, height, rgb = gifwriter.decode_png(os.path.join(REFERENCES, name))
    return width, height, bytes(
        0xC0 | ((rgb[i * 3] >> 6) << 4) | ((rgb[i * 3 + 1] >> 6) << 2)
        | (rgb[i * 3 + 2] >> 6) for i in range(width * height))


def lit_span(row):
    """(first lit index, count of lit pixels, count of partial pixels)."""
    lit = [i for i, c in enumerate(row) if c != "0"]
    partial = sum(1 for c in row if c in "12")
    return (lit[0] if lit else None), len(lit), partial


print("raster harness checks\n")

# ---------------------------------------------------------------------------
print("1. the four-level palette")
# Coverage is src_color.a = factor * 3 / 7 over a 0..8 factor, so a white-on-
# black render can only contain 0xC0, 0xD5, 0xEA, 0xFF.
frames = raster.gather(times=[(12, 0), (10, 10), (12, 1), (3, 0), (7, 38)])
check("off-palette bytes across 5 watchface renders",
      sum(f["other"] for f in frames), 0)
check("digit 9 (off-palette) in hand-made geometry",
      sum(r.count("9") for _, rows in geometry(["band 40 20 3 40 1"])
          for r in rows), 0)

# ---------------------------------------------------------------------------
print("\n2. the fill erodes 1 px and does not antialias vertical edges")
# Predicted: a 20 px wide band with vertical edges draws 19 px, and AA on is
# byte-identical to AA off, because delta is 0 and the blend factor is a full 8.
aa, non_aa = geometry(["band 40 20 0 40 1", "band 40 20 0 40 0"])
rows_aa = [r for r in aa[1] if r.count("0") != len(r)]
check("vertical band: AA output identical to non-AA", aa[1] == non_aa[1], True)
check("vertical band: lit width for 20 px of geometry",
      sorted({lit_span(r)[1] for r in rows_aa}), [19])
check("vertical band: partial-coverage pixels", 
      sum(lit_span(r)[2] for r in rows_aa), 0)

# ---------------------------------------------------------------------------
print("\n3. exactly 45 degrees is also drawn hard")
aa, non_aa = geometry(["band 40 20 40 40 1", "band 40 20 40 40 0"])
check("45-degree band: AA output identical to non-AA", aa[1] == non_aa[1], True)
rows45 = [r for r in aa[1] if r.count("0") != len(r)]
check("45-degree band: partial-coverage pixels",
      sum(lit_span(r)[2] for r in rows45), 0)

# ---------------------------------------------------------------------------
print("\n4. intermediate slopes get about one partial pixel per row")
aa, = geometry(["band 40 20 3 40 1"])
rows = [r for r in aa[1] if r.count("0") != len(r)]
partial = sum(lit_span(r)[2] for r in rows) / len(rows)
mean_width = sum(lit_span(r)[1] for r in rows) / len(rows)
check("lean 3: partial pixels per row is between 0.9 and 1.1",
      0.9 <= partial <= 1.1, True)
check("lean 3: mean lit width is between 19.3 and 19.6",
      19.3 <= mean_width <= 19.6, True)
notes.append(f"lean 3 over 40 rows: {partial:.2f} partial px/row, "
             f"mean lit width {mean_width:.2f} px for 20 px of geometry")

# ---------------------------------------------------------------------------
print("\n5. the 1 px outline skips AA at three specific slopes")
horiz, vert, diag, shallow = geometry([
    "line 40 40 80 40 1", "line 40 40 40 80 1",
    "line 40 40 80 80 1", "line 40 40 90 60 1"])
for label, frame in (("horizontal", horiz), ("vertical", vert),
                     ("45 degrees", diag)):
    check(f"{label} 1 px line: partial pixels",
          sum(r.count("1") + r.count("2") for r in frame[1]), 0)
shallow_partial = sum(r.count("1") + r.count("2") for r in shallow[1])
check("shallow 1 px line does antialias", shallow_partial > 0, True)
notes.append(f"shallow line 40,40-90,60: {shallow_partial} partial px")

# ---------------------------------------------------------------------------
print("\n6. the firmware's own trig table, not an approximation of it")
# sin_lookup is a 257-entry quarter-wave table with linear interpolation, and
# it is vendored. This measures what the harness would have cost had it kept
# using libm -- which is what every earlier sheet in this directory did.
every_minute = [(h, m) for h in range(12) for m in range(60)]
firmware = raster.gather(times=every_minute, want_frames=False)
libm = raster.gather(times=every_minute, want_frames=False, trig="libm")
differing = sum(1 for a, b in zip(firmware, libm) if a["hash"] != b["hash"])
ink = lambda f: sum(f["census"][1:])
worst = max(abs(ink(a) - ink(b)) for a, b in zip(firmware, libm))
check("all 720 minutes rendered with the firmware table", len(firmware), 720)
notes.append(f"libm instead of the vendored table would differ on "
             f"{differing}/720 frames, by up to {worst} lit pixels -- which is "
             f"why trig.c is vendored rather than approximated")

print("\n7. gabbro builds and renders too")
gab = raster.gather(times=[(10, 10)], board="gabbro")
check("gabbro frame size", (gab[0]["width"], gab[0]["height"]), (260, 260))
check("gabbro off-palette bytes", gab[0]["other"], 0)

# ---------------------------------------------------------------------------
print("\n8. the firmware's own test fixtures, diffed pixel for pixel")
# The strongest check available without a device: reproduce the geometry of the
# firmware's gpath unit tests and compare against its committed reference
# images. A self-crossing path is among them, which is the case the watchface
# actually relies on near hand overlap.
got = fixture_frames([name for name, _ in FIXTURES])
for (name, image), buffer in zip(FIXTURES, got):
    width, height, want = reference_frame(image)
    check(f"{name}: pixels differing from {image}",
          sum(1 for a, b in zip(buffer, want) if a != b), 0)
    check(f"{name}: byte count", len(buffer), width * height)
notes.append("no committed reference exists for an antialiased 1 px line at "
             "8-bit colour -- the draw_line fixtures are all for asterix, a "
             "1-bit board where antialiasing is compiled out. The outline pass "
             "rests on checks 5 above plus a shim surface that the bit-exact "
             "fill fixtures already cover.")

# ---------------------------------------------------------------------------
print("\n9. the raster ink lands exactly where the vector polygon says")
# Confirms the geometry wiring: same extraction, same overrides, so the drawn
# ink should occupy the same bounding box as the polygon vertices themselves.
cross = [(12, 0), (1, 5), (10, 10), (3, 0), (6, 33), (7, 38)]
vector = {(f["hour"], f["minute"]): f for f in sheet_envelope.gather(times=cross)}
rastered = {(f["hour"], f["minute"]): f for f in raster.gather(times=cross)}
worst_box, worst_scale = 0, 0.0
for key in cross:
    v, r = vector[key], rastered[key]
    xs = [p[0] for p in v["polygon"]]
    ys = [p[1] for p in v["polygon"]]
    box = (min(xs), min(ys), max(xs), max(ys))
    levels = raster.as_levels(r)
    ink_x = [x for row in levels for x, c in enumerate(row) if c]
    ink_y = [y for y, row in enumerate(levels) if any(row)]
    ink = (min(ink_x), min(ink_y), max(ink_x), max(ink_y))
    worst_box = max(worst_box, max(abs(a - b) for a, b in zip(box, ink)))
    worst_scale = max(worst_scale, abs(v["scale"] - r["scale"]))
    if v["pivot"] != r["pivot"]:
        failures.append(f"pivot index differs at {key}")
check("worst bounding-box disagreement with the vector polygon, px", worst_box, 0)
check("pivot index agrees on all six", 
      all(vector[k]["pivot"] == rastered[k]["pivot"] for k in cross), True)
notes.append(f"waist scale differs from the vector harness by up to "
             f"{worst_scale:.1e} -- that is the vector harness's libm trig, not "
             f"a wiring error; the raster figure is the correct one")

# ---------------------------------------------------------------------------
print("\n10. Python-built variants go through the same pipeline")
# The workshop sheets build some candidate envelopes in Python. That is only a
# fair comparison if the Python reproduction of the *shipped* envelope is
# pixel-identical to the C -- otherwise a row's difference could be an artefact
# of the reconstruction rather than the variant. It also catches the read loop
# in polygon_main.c silently stopping after one frame.
import sheet_workshop as workshop

t_times = ((12, 1), (12, 2), (12, 3), (12, 5), (12, 8))
built = raster.gather(times=t_times)
specs = []
for f in built:
    points = [(x, y) for x, y, _, _ in f["centerline"]]
    widths = [w for _, _, _, w in f["centerline"]]
    specs.append((workshop.polygon_from(points, widths,
                                        workshop.bisector_tangents(points)),
                  [(x, y) for x, y, _, _ in f["centerline"][f["pivot"]:]]))
replayed = raster.render_polygons(specs)
check("frames returned by render_polygons", len(replayed), len(t_times))
check("of them non-empty", sum(1 for r in replayed if sum(r["census"][1:])),
      len(t_times))
check("pixel-identical to the C-built envelope",
      sum(1 for a, b in zip(built, replayed) if a["buffer"] == b["buffer"]),
      len(t_times))

print()
for n in notes:
    print(f"  note: {n}")
print()
if failures:
    print(f"{len(failures)} check(s) FAILED: " + ", ".join(failures))
    raise SystemExit(1)
print("all checks passed")
