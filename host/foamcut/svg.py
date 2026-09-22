"""SVG -> closed polylines in millimetres, y up.

Reads what Inkscape and friends write: <path> (all commands, arcs included),
<rect>, <circle>, <ellipse>, <polygon>, <polyline>, <line>, nested <g> with
transforms. Text must be converted to paths first (Inkscape: Pfad -> Objekt
in Pfad umwandeln); <text> elements are reported, not silently dropped.

Units: the document's width/height/viewBox give the user-unit -> mm scale
(px at 96 dpi when unitless). SVG y grows downwards; here it grows upwards,
so the picture is not flipped on the machine.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

Point = tuple[float, float]

_UNIT_MM = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6, "px": 25.4 / 96, "": 25.4 / 96}
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


class SvgError(ValueError):
    pass


# ------------------------------------------------------------ transforms ---
Matrix = tuple[float, float, float, float, float, float]      # a b c d e f  (SVG order)
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mul(m: Matrix, n: Matrix) -> Matrix:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _apply(m: Matrix, p: Point) -> Point:
    a, b, c, d, e, f = m
    return (a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f)


def parse_transform(text: str | None) -> Matrix:
    m = IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        v = [float(x) for x in _NUM.findall(args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate":
            r = math.radians(v[0]); cs, sn = math.cos(r), math.sin(r)
            t = (cs, sn, -sn, cs, 0, 0)
            if len(v) == 3:
                cx, cy = v[1], v[2]
                t = _mul(_mul((1, 0, 0, 1, cx, cy), t), (1, 0, 0, 1, -cx, -cy))
        elif name == "skewX":
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY":
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = _mul(m, t)
    return m


# ------------------------------------------------------------- flattening --
def _bezier(pts: list[Point], n: int) -> list[Point]:
    """Points on a Bezier of any degree, t in (0, 1]."""
    out = []
    for k in range(1, n + 1):
        t = k / n
        p = list(pts)
        while len(p) > 1:
            p = [(p[i][0] + (p[i + 1][0] - p[i][0]) * t, p[i][1] + (p[i + 1][1] - p[i][1]) * t)
                 for i in range(len(p) - 1)]
        out.append(p[0])
    return out


def _segments_for(length: float, step: float) -> int:
    return max(4, int(math.ceil(length / step)))


def _arc(p0: Point, rx: float, ry: float, phi_deg: float, large: bool, sweep: bool, p1: Point, step: float) -> list[Point]:
    """SVG elliptical arc -> points (spec F.6.5, centre parameterisation)."""
    if p0 == p1:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [p1]
    phi = math.radians(phi_deg); cs, sn = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1p, y1p = cs * dx + sn * dy, -sn * dx + cs * dy
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(num / den, 0.0)) * (-1 if large == sweep else 1)
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = cs * cxp - sn * cyp + (p0[0] + p1[0]) / 2
    cy = sn * cxp + cs * cyp + (p0[1] + p1[1]) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    th1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    elif sweep and dth < 0:
        dth += 2 * math.pi
    n = _segments_for(abs(dth) * max(rx, ry), step)
    out = []
    for k in range(1, n + 1):
        th = th1 + dth * k / n
        x, y = rx * math.cos(th), ry * math.sin(th)
        out.append((cs * x - sn * y + cx, sn * x + cs * y + cy))
    out[-1] = p1
    return out


def path_to_polylines(d: str, step: float = 0.5) -> list[tuple[list[Point], bool]]:
    """A path's d attribute -> [(points, closed)] per subpath, user units."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + _NUM.pattern, d)
    out: list[tuple[list[Point], bool]] = []
    cur: list[Point] = []
    closed = False
    pos = (0.0, 0.0); start = (0.0, 0.0); last_ctrl: Point | None = None; last_cmd = ""
    i = 0
    cmd = ""

    def flush():
        nonlocal cur, closed
        if len(cur) > 1:
            out.append((cur, closed))
        cur, closed = [], False

    def num():
        nonlocal i
        v = float(tokens[i]); i += 1
        return v

    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t; i += 1
            if cmd in "Zz":
                closed = True
                flush()
                pos = start
                cur = []
                last_cmd = cmd
                continue
        elif cmd == "":
            raise SvgError("Pfad beginnt ohne Befehl")
        elif cmd == "M":
            cmd = "L"           # implicit lineto after moveto
        elif cmd == "m":
            cmd = "l"
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            x, y = num(), num()
            if rel:
                x, y = pos[0] + x, pos[1] + y
            flush()
            pos = start = (x, y); cur = [pos]
            last_ctrl = None
        elif c == "L":
            x, y = num(), num()
            pos = (pos[0] + x, pos[1] + y) if rel else (x, y)
            cur.append(pos); last_ctrl = None
        elif c == "H":
            x = num(); pos = (pos[0] + x if rel else x, pos[1]); cur.append(pos); last_ctrl = None
        elif c == "V":
            y = num(); pos = (pos[0], pos[1] + y if rel else y); cur.append(pos); last_ctrl = None
        elif c in "CS":
            if c == "C":
                c1 = (num(), num())
            else:
                c1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl and last_cmd.upper() in "CS" else pos
            c2 = (num(), num()); p1 = (num(), num())
            if rel:
                if c == "C":
                    c1 = (pos[0] + c1[0], pos[1] + c1[1])
                c2 = (pos[0] + c2[0], pos[1] + c2[1]); p1 = (pos[0] + p1[0], pos[1] + p1[1])
            n = _segments_for(math.dist(pos, c1) + math.dist(c1, c2) + math.dist(c2, p1), step)
            cur.extend(_bezier([pos, c1, c2, p1], n))
            last_ctrl = c2; pos = p1
        elif c in "QT":
            if c == "Q":
                c1 = (num(), num())
                if rel:
                    c1 = (pos[0] + c1[0], pos[1] + c1[1])
            else:
                c1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl and last_cmd.upper() in "QT" else pos
            p1 = (num(), num())
            if rel:
                p1 = (pos[0] + p1[0], pos[1] + p1[1])
            n = _segments_for(math.dist(pos, c1) + math.dist(c1, p1), step)
            cur.extend(_bezier([pos, c1, p1], n))
            last_ctrl = c1; pos = p1
        elif c == "A":
            rx, ry, rot = num(), num(), num()
            large, sweep = num() != 0, num() != 0
            p1 = (num(), num())
            if rel:
                p1 = (pos[0] + p1[0], pos[1] + p1[1])
            cur.extend(_arc(pos, rx, ry, rot, large, sweep, p1, step))
            pos = p1; last_ctrl = None
        else:
            raise SvgError(f"Pfadbefehl {cmd!r} nicht unterstuetzt")
        last_cmd = cmd
    flush()
    return out


# ---------------------------------------------------------------- shapes ---
def _attr(el, name: str, default: float = 0.0) -> float:
    v = el.get(name)
    if v is None:
        return default
    m = _NUM.search(v)
    return float(m.group(0)) if m else default


def _ellipse(cx, cy, rx, ry, step) -> list[Point]:
    n = _segments_for(2 * math.pi * max(rx, ry), step)
    return [(cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _rect(x, y, w, h, rx, ry, step) -> list[Point]:
    rx, ry = min(rx, w / 2), min(ry, h / 2)
    if rx <= 0 or ry <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    pts = []
    n = _segments_for(math.pi / 2 * max(rx, ry), step)
    for (cx, cy, a0) in ((x + w - rx, y + ry, -math.pi / 2), (x + w - rx, y + h - ry, 0.0),
                         (x + rx, y + h - ry, math.pi / 2), (x + rx, y + ry, math.pi)):
        for k in range(n + 1):
            a = a0 + math.pi / 2 * k / n
            pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    return pts


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element_loops(el, m: Matrix, step: float, texts: list[str]) -> list[list[Point]]:
    tag = _local(el.tag)
    loops: list[list[Point]] = []
    if tag == "path":
        for pts, closed in path_to_polylines(el.get("d", ""), step):
            if closed or (len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6):
                loops.append(pts)
            elif len(pts) > 2:
                loops.append(pts)           # open path: closed by the straight line back
    elif tag == "rect":
        loops.append(_rect(_attr(el, "x"), _attr(el, "y"), _attr(el, "width"), _attr(el, "height"),
                           _attr(el, "rx", _attr(el, "ry")), _attr(el, "ry", _attr(el, "rx")), step))
    elif tag == "circle":
        r = _attr(el, "r"); loops.append(_ellipse(_attr(el, "cx"), _attr(el, "cy"), r, r, step))
    elif tag == "ellipse":
        loops.append(_ellipse(_attr(el, "cx"), _attr(el, "cy"), _attr(el, "rx"), _attr(el, "ry"), step))
    elif tag in ("polygon", "polyline"):
        v = [float(x) for x in _NUM.findall(el.get("points", ""))]
        pts = list(zip(v[0::2], v[1::2]))
        if len(pts) > 2:
            loops.append(pts)
    elif tag == "text":
        texts.append("".join(el.itertext()).strip() or "<text>")
    out = []
    for pts in loops:
        pts = [_apply(m, p) for p in pts]
        if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-9:
            pts = pts[:-1]
        if len(pts) > 2:
            out.append(pts)
    return out


def _walk(el, m: Matrix, step: float, texts: list[str], out: list[list[Point]]):
    tag = _local(el.tag)
    if tag in ("defs", "clipPath", "mask", "marker", "symbol", "metadata", "style"):
        return
    m = _mul(m, parse_transform(el.get("transform")))
    out.extend(_element_loops(el, m, step, texts))
    for child in el:
        _walk(child, m, step, texts, out)


def _length_mm(v: str | None) -> float | None:
    if not v:
        return None
    m = re.match(r"\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)\s*([a-z%]*)", v)
    if not m or m.group(2) == "%":
        return None
    return float(m.group(1)) * _UNIT_MM.get(m.group(2), _UNIT_MM[""])


def load_svg(path: Path, step_mm: float = 0.5) -> tuple[list[list[Point]], list[str]]:
    """All closed outlines of an SVG file in mm, y up, plus warnings."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise SvgError(f"{path}: kein gueltiges SVG ({e})") from None
    if _local(root.tag) != "svg":
        raise SvgError(f"{path}: kein SVG-Dokument")
    vb = [float(x) for x in _NUM.findall(root.get("viewBox", ""))]
    w_mm, h_mm = _length_mm(root.get("width")), _length_mm(root.get("height"))
    if len(vb) == 4:
        vx, vy, vw, vh = vb
    else:
        vx, vy = 0.0, 0.0
        vw = (w_mm / _UNIT_MM[""]) if w_mm else 0.0
        vh = (h_mm / _UNIT_MM[""]) if h_mm else 0.0
    scale = (w_mm / vw) if (w_mm and vw) else _UNIT_MM[""]
    if not vh:
        vh = (h_mm / scale) if h_mm else 0.0
    texts: list[str] = []
    raw: list[list[Point]] = []
    _walk(root, IDENTITY, step_mm / scale, texts, raw)
    warnings = []
    if texts:
        warnings.append("Text nicht umgewandelt (Inkscape: Pfad -> Objekt in Pfad umwandeln): " + ", ".join(texts[:5]))
    if not raw:
        raise SvgError(f"{path}: keine geschlossenen Konturen gefunden")
    if not vh:
        vh = max(p[1] for loop in raw for p in loop)
    loops = [[((x - vx) * scale, (vy + vh - y) * scale) for x, y in loop] for loop in raw]
    return loops, warnings
