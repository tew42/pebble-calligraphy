# Connector pivot preview harness

Explores how the **centerline** of the Calligraphy stroke bends through the
middle, where the hour and minute stems are joined. Pure Python 3, standard
library only -- no numpy, matplotlib, PIL or cairo. Output is hand-written SVG.

```sh
cd tools/preview
python3 report.py --all          # every sheet plus out/metrics.md  (~25 s)
python3 test_harness.py          # self-checks
```

Individual sheets: `--grid --zoom --curvature --ceiling --tilt --stems
--profiles --locus --metrics --filmstrip`.

Animations are two steps, because rasterizing needs a browser:

```sh
python3 report.py --anim            # 60 per-frame SVGs per layout
./render_anim.sh anim-current       # rasterize + encode  (~1 min)
./render_anim.sh anim-stems
```

`--anim-hour` picks the hour (default 12, which starts on exact overlap); over
one hour the separation runs 0 -> 178.5 -> 35.5 deg, so a single loop passes
through overlap, near-opposition and the mid-range twice.
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
| `compare-zoom.svg` | the centre region at 2.6x -- where the shape is judged |
| `curvature-profiles.svg` | \|k\| along the connector -- **the unimodality test** |
| `ceiling.svg` | the measured unimodal region vs the closed-form ceiling |
| `tilt-grid.svg` | the beta bracket, zoomed: how much asymmetry is available |
| `stems-grid.svg` | does the rule survive a change of stem geometry |
| `profiles.svg` | pivot depth s(delta) for every candidate on one axis |
| `pivot-locus.svg` | the pivot's path over a full 12 hours -- 11-lobed rosettes |
| `anim-current.gif` | D1 / D3 / C3 over an hour, current stems |
| `anim-stems.gif` | D1 and C3 over an hour, four stem configurations |
| `anim-filmstrip.svg` | the same hour as a static 12-frame contact sheet |
| `metrics.md` | all 720 positions x 17 candidates x 6 stem configs |
| `ceiling.json` | the bisected unimodality limit, cached |

In the sheets: **white** = candidate, **amber** = C0, the current construction,
drawn as a reference underlay, **blue** = the pivot, **dashed** = the tangent
triangle A-B-centre.

## Where things live

- `geometry.py` -- the port, the `(mu, beta)` pivot family, the two ceilings
  (`chord_ceiling` and the binding `arc_apex_ceiling`), the candidate registry
  and the stem configurations. Stem radii and hand lengths are parameters, so
  every candidate can be swept over alternative geometries.
- `svgcanvas.py` -- the SVG writer.
- `report.py` -- metrics, sheet generation, animation frame sequences.
- `render_anim.sh` -- the only part needing an external binary: Chromium
  (`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, overridable with
  `CHROME=`) to rasterize the frames. Override the output scale with `SCALE=2`.
- `gifwriter.py` -- PNG -> animated GIF, standard library only. Exists because
  Chromium writes only PNG and the bundled ffmpeg is a stripped Playwright build
  with no GIF encoder (libvpx only), so neither tool can close the loop.
- `test_harness.py` -- invariants: construction fidelity, tangent-triangle
  containment, stem homogeneity and mirror symmetry, curvature continuity, and
  unimodality of the round-2 depth rules across every stem configuration (with
  the illustration candidates asserted to *fail*, so the sheets keep making
  their point).

Two metric guards worth knowing about, because without them the numbers lie:
a curvature dip is only counted where peak |k| exceeds a 1000 px radius **and**
the connector departs from its chord by at least half a pixel. Near opposition
the geometry is sub-pixel by design, and measuring a dip in floating-point noise
otherwise yields 100% readings from nothing.

The reasoning and the recommendation live in [`docs/pivot-design.md`](../../docs/pivot-design.md).
