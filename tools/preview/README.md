# Connector pivot preview harness

Explores how the **centerline** of the Calligraphy stroke bends through the
middle, where the hour and minute stems are joined. Pure Python 3, standard
library only -- no numpy, matplotlib, PIL or cairo. Output is hand-written SVG.

```sh
cd tools/preview
python3 report.py --all          # every sheet plus out/metrics.md  (~25 s)
python3 test_harness.py          # self-checks
```

Individual sheets: `--grid --zoom --tilt --stems --profiles --locus --metrics`.
Useful flags: `--times 12:00,3:00,4:50`, `--stem-config symmetric`.

## Scope

This models **the line only** -- the path the pen travels. It deliberately does
*not* reproduce:

- the stroke, the width profile, or the pressure/clearance modulation,
- `gpath_draw_filled` / `gpath_draw_outline` rasterization,
- the antialiasing passes or the minute pixel core.

What it does mirror faithfully, from `src/c/main.c`: the integer trig lookup, the
radial stem construction, the four-unknown minimum-bending-energy tangent solve
with its Gauss-Jordan solver and fallback, the arc-proportional guide index with
its clamp, and the 49-point Hermite sampling. The polylines drawn in the sheets
are the same 49 points the device draws.

One deliberate deviation: `sin_lookup` rounds an exact sine to the table's
fixed-point resolution rather than reading the firmware's precomputed table.
Any disagreement is below 1/65535 of a hand length -- far under a pixel.

## Outputs (`out/`, gitignored)

| file | what it answers |
|---|---|
| `compare-grid.svg` | how each candidate looks on the whole face |
| `compare-zoom.svg` | the centre region at 2.6x -- **where the decision is made** |
| `tilt-grid.svg` | the beta bracket, zoomed: how much asymmetry is available |
| `stems-grid.svg` | does the rule survive a change of stem geometry |
| `profiles.svg` | pivot depth s(delta) for every candidate on one axis |
| `pivot-locus.svg` | the pivot's path over a full 12 hours -- 11-lobed rosettes |
| `metrics.md` | all 720 positions x 12 candidates x 6 stem configs |

In the sheets: **white** = candidate, **amber** = C0, the current construction,
drawn as a reference underlay, **blue** = the pivot, **dashed** = the tangent
triangle A-B-centre.

## Where things live

- `geometry.py` -- the port, the `(mu, beta)` pivot family, the candidate registry
  and the stem configurations. Stem radii and hand lengths are parameters, so
  every candidate can be swept over alternative geometries.
- `svgcanvas.py` -- the SVG writer.
- `report.py` -- metrics and sheet generation.
- `test_harness.py` -- invariants: construction fidelity, tangent-triangle
  containment, stem homogeneity and mirror symmetry, curvature continuity.

The reasoning and the recommendation live in [`docs/pivot-design.md`](../../docs/pivot-design.md).
