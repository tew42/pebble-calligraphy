#!/usr/bin/env python3
"""Check the pivot rule in src/c/main.c against the Python reference.

    python3 tools/preview/check_c_pivot.py

Everything else in this directory is a model of the watchface.  This is the one
script that tests the watchface itself: it lifts `calculate_pivot_point` and the
handful of vector helpers it uses straight out of `main.c`, compiles them, and
compares the result against `geometry.py`'s D1 rule at every hand position in
every stem configuration.  If the two ever disagree, either the C was edited
without the model or the model was edited without the C.

Needs a C compiler, which nothing else here does, so it is a separate script
rather than part of test_harness.py.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as G

MAIN_C = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "src", "c", "main.c")

#: Lifted verbatim, in dependency order.
WANTED = (
    "static float clamp_float(",
    "static float square_root_float(",
    "static Vec2 make_vec2(",
    "static Vec2 add_vec2(",
    "static Vec2 subtract_vec2(",
    "static Vec2 multiply_vec2(",
    "static float dot_vec2(",
    "static float length_vec2(",
    "static Vec2 normalize_vec2(",
    "static float distance_between(",
    "static Vec2 direction_between(",
    "static Vec2 calculate_pivot_point(",
)

#: float32 against float64, over a 100 px face.
TOLERANCE_PX = 1e-3

DRIVER = """
int main(void) {
  float cx, cy, ax, ay, bx, by;
  while (scanf("%f %f %f %f %f %f", &cx, &cy, &ax, &ay, &bx, &by) == 6) {
    Vec2 c = { cx, cy }, a = { ax, ay }, b = { bx, by };
    Vec2 p = calculate_pivot_point(c, a, b);
    printf("%.9f %.9f\\n", p.x, p.y);
  }
  return 0;
}
"""


def extract(source: str, signature: str) -> str:
    """One function, by brace matching from its signature."""
    start = source.index(signature)
    depth, index = 0, source.index("{", start)
    while True:
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    return source[start:index + 1] + "\n"


def build(directory: str) -> str:
    source = open(MAIN_C).read()
    epsilon = re.search(r"#define VECTOR_EPSILON (\S+)", source).group(1)
    pieces = [
        "#include <stdio.h>",
        "#include <stdint.h>",
        "#include <stdbool.h>",
        f"#define VECTOR_EPSILON {epsilon}",
        "typedef struct {\n  float x;\n  float y;\n} Vec2;",
    ]
    pieces += [extract(source, signature) for signature in WANTED]
    pieces.append(DRIVER)

    path = os.path.join(directory, "pivot.c")
    open(path, "w").write("\n".join(pieces))
    binary = os.path.join(directory, "pivot")
    subprocess.run(["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                    "-o", binary, path, "-lm"], check=True)
    return binary


def main() -> int:
    rule = G.CANDIDATES_BY_KEY["d1-arc-sin"].rule
    face = G.Face()
    cases, expected = [], []
    for stems in G.STEM_CONFIGS:
        for hour, minute in G.ALL_TIMES:
            cl = G.build_centerline(hour, minute, rule, face, stems)
            centre = cl.context.center
            a, b = cl.hour_connector, cl.minute_connector
            cases.append(f"{centre[0]:.9f} {centre[1]:.9f} {a[0]:.9f} "
                         f"{a[1]:.9f} {b[0]:.9f} {b[1]:.9f}")
            expected.append((cl.pivot, stems.name, hour, minute))

    with tempfile.TemporaryDirectory() as directory:
        binary = build(directory)
        print(f"compiled {len(WANTED)} functions out of main.c, no warnings")
        output = subprocess.run([binary], input="\n".join(cases) + "\n",
                                capture_output=True, text=True, check=True)

    got = [tuple(float(v) for v in line.split())
           for line in output.stdout.splitlines()]
    if len(got) != len(expected):
        print(f"FAIL: {len(got)} results for {len(expected)} cases")
        return 1

    worst = (0.0, None)
    for (point, name, hour, minute), c_point in zip(expected, got):
        error = G.norm(G.sub(c_point, point))
        if error > worst[0]:
            worst = (error, (name, hour, minute))

    overlap_worst = 0.0
    for (point, name, hour, minute), c_point in zip(expected, got):
        if G.separation_degrees(hour, minute) < 1e-9:
            overlap_worst = max(overlap_worst,
                                G.norm(G.sub(c_point, face.center)))

    print(f"checked {len(got)} positions across {len(G.STEM_CONFIGS)} stem "
          f"configurations")
    print(f"  worst disagreement with the model: {worst[0]:.2e} px at {worst[1]}")
    print(f"  pivot at exact overlap, worst over configs: {overlap_worst:.2e} px "
          "from the centre")
    if worst[0] > TOLERANCE_PX:
        print(f"FAIL: above the {TOLERANCE_PX} px tolerance")
        return 1
    if overlap_worst != 0.0:
        print("FAIL: the pivot must be exactly on the centre at overlap")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
