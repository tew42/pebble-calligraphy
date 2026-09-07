# Pivot-geometry study

Offline harness used to explore how the central connector of the Calligraphy
centreline should be derived. Pure Python, no dependencies; renders SVG directly.

    python3 render_study.py     # -> out/study.html   (working comparison grid)
    python3 build_artifact.py   # -> out/pivot-study.html (write-up)

`pivot_study.py` holds a faithful port of the shipping construction in
`src/c/main.c` (`calculate_pivot_point`, the 4x4 bending solver, the two-piece
cubic Hermite) plus the candidate constructions, so alternatives are measured
against the real geometry rather than an approximation of it.

All figures are in watch units: R = 100 px, the inscribed radius of the
200 x 228 emery / gabbro display.

Key measurement: the closest approach of the centreline to the true watch
centre, per minute over the full 720-minute cycle.

Nothing here is built into the watchapp; `src/` is untouched.
