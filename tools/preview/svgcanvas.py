"""A very small hand-rolled SVG writer.

Exists so the preview harness has zero third-party dependencies -- this
container has no numpy, matplotlib, PIL or cairo, and none are needed to draw
polylines.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Palette: white-on-black, matching how the watchface actually renders.
INK = "#ffffff"          # the candidate centerline
REFERENCE = "#ff8a3d"    # the current construction, as a faint underlay
GUIDE = "#38475a"        # tangent triangle, hairlines
PIVOT = "#4fc3f7"        # the pivot point
TIP = "#8b98a8"          # hand tips / stem ends
PANEL = "#0d0f12"
PAGE = "#16191d"
LABEL = "#c9d3de"
DIM = "#7c8996"
RAMP = ("#f4d35e", "#ee964b", "#f95d6a", "#a05195", "#4a6fa5")

# The only four values a white-on-black render can contain.  Coverage is
# quantized to src_color.a = factor * 3 / 7 over a 0..8 factor, so there are two
# intermediate greys and no more -- these are the real 2-bit-per-channel values
# expanded to 8 bits, not an even ramp.
PIXEL_LEVELS = ("#000000", "#555555", "#aaaaaa", "#ffffff")


def esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


@dataclass
class Canvas:
    width: float
    height: float
    background: str = PAGE
    parts: list[str] = field(default_factory=list)

    # -- primitives --------------------------------------------------------

    def rect(self, x, y, w, h, fill="none", stroke="none", stroke_width=1.0,
             opacity=1.0, rx=0.0):
        self.parts.append(
            f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" '
            f'rx="{fmt(rx)}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{fmt(stroke_width)}" opacity="{fmt(opacity)}"/>'
        )

    def polyline(self, points, stroke=INK, stroke_width=1.4, opacity=1.0,
                 dash=None, fill="none", close=False):
        if len(points) < 2:
            return
        data = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in points)
        tag = "polygon" if close else "polyline"
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<{tag} points="{data}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{fmt(stroke_width)}" stroke-linecap="round" '
            f'stroke-linejoin="round" opacity="{fmt(opacity)}"{extra}/>'
        )

    def polygon(self, points, fill=INK, stroke="none", stroke_width=0.0,
                opacity=1.0) -> None:
        """A closed filled path, drawn as a vector.

        Diagram use only.  This is *not* how the watch fills a path: the
        firmware erodes each span by a pixel, puts partial coverage on the
        interior side of the edge, and quantizes it to four levels, none of
        which a browser polygon reproduces.  Anything being judged on how it
        will actually look wants `pixels()` and a framebuffer from raster.py.
        The `fill-rule` below happens to match the firmware's nonzero winding,
        but the resemblance stops there."""
        coordinates = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in points)
        self.parts.append(
            f'<polygon points="{coordinates}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{fmt(stroke_width)}" '
            f'fill-rule="nonzero" opacity="{fmt(opacity)}"/>'
        )

    def pixels(self, x, y, rows, scale=1.0, palette=None, gap=0.0) -> None:
        """Draw a framebuffer as actual pixels, magnified by `scale`.

        `rows` is a list of rows of small integers -- what raster.as_levels
        returns -- and `palette` maps those to colours, defaulting to the four
        levels the device can produce.  Runs of equal value within a row become
        one rect, which keeps a full 200x228 frame to a few hundred elements
        instead of 45,600, so a multi-panel sheet stays cheap.  Level 0 is the
        background and is not emitted at all.

        Deliberately no smoothing and no image element: a pixel is a rect of
        exactly `scale` units, so what is on the sheet is what is in the
        framebuffer.  `gap` insets each rect slightly, which at large
        magnifications makes the pixel grid itself legible.
        """
        colours = palette or PIXEL_LEVELS
        for row_index, row in enumerate(rows):
            column = 0
            width = len(row)
            while column < width:
                value = row[column]
                run = 1
                while column + run < width and row[column + run] == value:
                    run += 1
                if value:
                    self.rect(x + column * scale + gap * 0.5,
                              y + row_index * scale + gap * 0.5,
                              run * scale - gap, scale - gap,
                              fill=colours[value])
                column += run

    def line(self, x1, y1, x2, y2, stroke=GUIDE, stroke_width=0.6, opacity=1.0,
             dash=None):
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<line x1="{fmt(x1)}" y1="{fmt(y1)}" x2="{fmt(x2)}" y2="{fmt(y2)}" '
            f'stroke="{stroke}" stroke-width="{fmt(stroke_width)}" '
            f'opacity="{fmt(opacity)}"{extra}/>'
        )

    def circle(self, cx, cy, r, fill=PIVOT, stroke="none", stroke_width=0.0,
               opacity=1.0):
        self.parts.append(
            f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(r)}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{fmt(stroke_width)}" '
            f'opacity="{fmt(opacity)}"/>'
        )

    def text(self, x, y, content, size=10.0, fill=LABEL, anchor="start",
             weight="400", family="ui-monospace, SFMono-Regular, Menlo, monospace",
             opacity=1.0):
        self.parts.append(
            f'<text x="{fmt(x)}" y="{fmt(y)}" font-size="{fmt(size)}" '
            f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" '
            f'font-family="{family}" opacity="{fmt(opacity)}">{esc(content)}</text>'
        )

    # -- grouping ----------------------------------------------------------

    def push_clip(self, x, y, w, h, name: str) -> None:
        self.parts.append(
            f'<defs><clipPath id="{name}"><rect x="{fmt(x)}" y="{fmt(y)}" '
            f'width="{fmt(w)}" height="{fmt(h)}"/></clipPath></defs>'
            f'<g clip-path="url(#{name})">'
        )

    def pop(self) -> None:
        self.parts.append("</g>")

    # -- output ------------------------------------------------------------

    def to_svg(self) -> str:
        body = "\n".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(self.width)}" '
            f'height="{fmt(self.height)}" viewBox="0 0 {fmt(self.width)} '
            f'{fmt(self.height)}">\n'
            f'<rect width="100%" height="100%" fill="{self.background}"/>\n'
            f"{body}\n</svg>\n"
        )

    def write(self, path) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.to_svg())
