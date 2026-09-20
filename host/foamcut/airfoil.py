"""Airfoil coordinate files (.dat) - reading, normalising, resampling.

Two formats are in the wild:

  Selig     name, then one loop of x y pairs: trailing edge -> upper surface
            -> leading edge -> lower surface -> trailing edge. Chord = 1.
  Lednicer  name, then a line with the two point counts, then upper surface
            LE -> TE, blank line, lower surface LE -> TE.

Both come out of `load()` as (upper, lower), each a list of (x, y) running
from the leading edge (x = 0) to the trailing edge (x = 1).
"""
from __future__ import annotations

import math
from pathlib import Path

Point = tuple[float, float]
Surface = list[Point]


class AirfoilError(ValueError):
    pass


def _pairs(lines: list[str]) -> list[Point]:
    out = []
    for line in lines:
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            out.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return out


def parse(text: str) -> tuple[str, Surface, Surface]:
    """-> (name, upper LE->TE, lower LE->TE), chord normalised to 1."""
    lines = [l.rstrip() for l in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        raise AirfoilError("leere Datei")
    name = lines[0].strip()
    body = lines[1:]
    pts = _pairs(body)
    if len(pts) < 6:
        raise AirfoilError(f"{name!r}: zu wenige Koordinaten")

    # Lednicer: first numeric line holds the point counts (values > 1)
    if pts[0][0] > 1.5 and pts[0][1] > 1.5:
        n_up, n_lo = int(round(pts[0][0])), int(round(pts[0][1]))
        rest = pts[1:]
        if len(rest) < n_up + n_lo:
            raise AirfoilError(f"{name!r}: Lednicer-Zaehler passen nicht zu den Daten")
        upper, lower = rest[:n_up], rest[n_up:n_up + n_lo]
    else:
        # Selig: split the loop at the leading edge (smallest x)
        i_le = min(range(len(pts)), key=lambda i: pts[i][0])
        upper = list(reversed(pts[:i_le + 1]))     # TE..LE reversed -> LE..TE
        lower = pts[i_le:]                          # LE..TE
        if len(upper) < 3 or len(lower) < 3:
            raise AirfoilError(f"{name!r}: Nasenleiste nicht gefunden")

    return name, _normalise(upper), _normalise(lower)


def _normalise(surface: Surface) -> Surface:
    """Sort by x, drop duplicates, clamp to [0, 1]."""
    pts = sorted({(round(x, 7), y) for x, y in surface})
    if not pts:
        return []
    x0, x1 = pts[0][0], pts[-1][0]
    if x1 - x0 < 0.5:
        raise AirfoilError("Profil hat keine sinnvolle Sehne")
    scale = 1.0 / (x1 - x0)
    return [((x - x0) * scale, y * scale) for x, y in pts]


def load(path: Path) -> tuple[str, Surface, Surface]:
    return parse(Path(path).read_text(errors="replace"))


def _interp(surface: Surface, x: float) -> float:
    """Linear interpolation of y at x on a surface sorted by x."""
    if x <= surface[0][0]:
        return surface[0][1]
    if x >= surface[-1][0]:
        return surface[-1][1]
    lo, hi = 0, len(surface) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if surface[mid][0] <= x:
            lo = mid
        else:
            hi = mid
    (xa, ya), (xb, yb) = surface[lo], surface[hi]
    if xb == xa:
        return ya
    return ya + (yb - ya) * (x - xa) / (xb - xa)


def cosine_spacing(n: int) -> list[float]:
    """n values in [0, 1], dense at both ends - where the curvature is."""
    return [0.5 * (1.0 - math.cos(math.pi * k / (n - 1))) for k in range(n)]


def resample_loop(upper: Surface, lower: Surface, n: int) -> list[Point]:
    """One cutting loop TE -> upper -> LE -> lower -> TE with 2n-1 points.

    Both surfaces get the same x stations, so two different airfoils
    resampled with the same n have point-for-point correspondence - which is
    what a tapered wing needs to pair root and tip points on the wire.
    """
    xs = cosine_spacing(n)
    up = [(x, _interp(upper, x)) for x in reversed(xs)]   # TE -> LE
    lo = [(x, _interp(lower, x)) for x in xs[1:]]         # LE -> TE, skip the LE twice
    return up + lo


def offset_loop(loop: list[Point], distance: float) -> list[Point]:
    """Offset a closed counter-clockwise loop outward by `distance`.

    Used for kerf: the wire melts a channel wider than itself, so the path
    runs half the kerf outside the wanted contour.
    """
    if abs(distance) < 1e-12:
        return list(loop)
    n = len(loop)
    out = []
    for i, (x, y) in enumerate(loop):
        (xa, ya) = loop[i - 1] if i > 0 else loop[-2]           # loop[0] == loop[-1] (TE)
        (xb, yb) = loop[i + 1] if i < n - 1 else loop[1]
        tx, ty = xb - xa, yb - ya
        length = math.hypot(tx, ty) or 1.0
        nx, ny = ty / length, -tx / length                         # right of travel = outward on CCW
        out.append((x + nx * distance, y + ny * distance))
    return out
