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
