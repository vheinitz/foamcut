"""Free shapes in one pass: a convex cross-section on each side (rounded
rectangle, triangle, circle, ellipse), as a disc or a ring, lofted by the
wire between the two block faces. Fuselage segments, spacers, wheels, ...

The two sides need not be the same kind: every contour is resampled at the
same angles from its centre, so point i on side A pairs with point i on side
B and the wire sweeps a ruled surface between them. A ring is cut through a
slit at the rear: outer contour, straight in to the hole, hole, straight out.

Placement (block face, table, margins, block) is the same as for wings and
lives in wing.loft(); the text format mirrors .wing files.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from . import airfoil as af
from .machine import Machine
from .wing import (Model, WingError, WingPath, _template, emit_gcode, field_catalogue, from_text, loft,
                   to_text)

KINDS = ("rechteck", "dreieck", "kreis", "ellipse")
HOLES = ("keine",) + KINDS

_SIDE_HELP = {
    "kind": "Grundform des Querschnitts: Rechteck oder Dreieck (Grundseite unten, Spitze oben) mit "
            "Eckenradius, Kreis (Breite = Hoehe) oder Ellipse.",
    "w": "Breite in X (vorn-hinten).",
    "h": "Hoehe in Y. Beim Kreis wird die Breite genommen.",
    "r": "Eckenradius bei Rechteck/Dreieck; 0 = scharfe Ecken, bei Kreis/Ellipse ohne Wirkung.",
    "hole": "Loch in der Mitte fuer einen Ring, gleiche Formen wie aussen. Der Draht schneidet "
            "aussen herum, dann durch einen Schlitz hinten zum Loch, das Loch, und wieder hinaus. "
            "Beide Seiten brauchen ein Loch oder keines.",
    "hole_w": "Breite des Lochs in X.",
    "hole_h": "Hoehe des Lochs in Y (Kreis: Breite).",
    "hole_r": "Eckenradius des Lochs bei Rechteck/Dreieck.",
}


def _side(prefix: str, title: str, dx: bool) -> tuple:
    fields = [
        (f"{prefix}_kind", "Form", "", "rechteck", _SIDE_HELP["kind"], "choice:" + "|".join(KINDS)),
        (f"{prefix}_w", "Breite X", "mm", "60", _SIDE_HELP["w"], "num"),
        (f"{prefix}_h", "Hoehe Y", "mm", "40", _SIDE_HELP["h"], "num"),
        (f"{prefix}_r", "Eckenradius", "mm", "8", _SIDE_HELP["r"], "num"),
    ]
    if dx:
        fields += [
            (f"{prefix}_dx", "Versatz X", "mm", "0",
             "Mittelpunkt dieser Seite gegenueber Seite A in X (positiv = nach vorn).", "num"),
            (f"{prefix}_dy", "Versatz Y", "mm", "0",
             "Mittelpunkt dieser Seite gegenueber Seite A in Y (positiv = nach oben).", "num"),
        ]
    fields += [
        (f"{prefix}_hole", "Loch", "", "keine", _SIDE_HELP["hole"], "choice:" + "|".join(HOLES)),
        (f"{prefix}_hole_w", "Loch Breite X", "mm", "20", _SIDE_HELP["hole_w"], "num"),
        (f"{prefix}_hole_h", "Loch Hoehe Y", "mm", "20", _SIDE_HELP["hole_h"], "num"),
        (f"{prefix}_hole_r", "Loch Eckenradius", "mm", "0", _SIDE_HELP["hole_r"], "num"),
    ]
    return (prefix, title, fields)


FIELDS = [
    ("form", "Form", [
        ("panel", "Laenge", "mm", "200",
         "Laenge des Stuecks in Spannrichtung, von Seite A (am Turm mit festem Draht) bis Seite B.", "num"),
        ("points", "Stuetzpunkte", "", "72",
         "Punkte je Umfang (aussen und Loch). Mehr = runder, mehr G-Code-Zeilen.", "int"),
    ]),
    _side("a", "Seite A (Wurzel)", dx=False),
    _side("b", "Seite B (Ende)", dx=True),
    ("lage", "Lage im Schneider", [
        ("root_gap", "Seite A ab Turm", "mm", "150",
         "Abstand der Seite A des Blocks vom Turm mit dem festen Draht, entlang des Drahts.", "num"),
        ("block_x", "Block Rueckseite X", "mm", "20",
         "Abstand der Blockrueckseite vom Referenzpunkt nach vorn. Dort taucht der Draht ein.", "num"),
        ("table_y", "Tischoberkante Y", "mm", "20",
         "Hoehe der Tischoberkante (= Blockunterkante) ueber dem Draht-Null. Die Form liegt 'Rand' darueber.", "num"),
        ("lead", "Einlauf", "mm", "12",
         "Strecke im Schaum von der Blockrueckseite bis zum hintersten Punkt der Form.", "num"),
    ]),
    ("schnitt", "Schnitt", [
        ("feed", "Drahtvorschub", "mm/min", "200",
         "Geschwindigkeit des Drahts im Schaum, bezogen auf die schnellere der beiden Seiten.", "num"),
        ("wire", "Heizleistung S", "1..255", "0",
         "PWM-Stufe des Heizdrahts. 0 = Wert vom Schieber im Hauptfenster uebernehmen.", "int"),
        ("warmup", "Aufheizen", "s", "3", "Wartezeit nach dem Einschalten des Drahts.", "num"),
        ("kerf", "Schnittbreite", "mm", "1.0",
         "Breite des Schmelzkanals. Aussen laeuft der Pfad die Haelfte davon ausserhalb, im Loch innerhalb.", "num"),
        ("margin", "Rand", "mm", "10",
         "Mindestabstand der Form zu Vorderseite, Ober-, Unterseite und Seite B des Blocks.", "num"),
    ]),
    ("block", "Block", [
        ("block_s", "Block Anfang ab Seite A", "mm", "", "0 oder leer = der Block beginnt an Seite A.", "num"),
        ("block_w", "Block Breite", "mm", "", "Ausdehnung in Spannrichtung. Leer = Laenge plus Rand.", "num"),
        ("block_len", "Block Laenge", "mm", "", "Leer = Mindestblock.", "num"),
        ("block_h", "Block Hoehe", "mm", "", "Ab Tischoberkante. Leer = Mindestblock.", "num"),
    ]),
]

TEMPLATE = _template(FIELDS, ("; Freie Form fuer den Schaumschneider: ein Querschnitt je Seite, Scheibe oder Ring.",
                              "; Alle Masse in mm. Zeilen mit ; sind Kommentare."))
_CHOICES = {key: kind.split(":", 1)[1].split("|")
            for key, (_, _, _, _, kind) in field_catalogue(FIELDS).items() if kind.startswith("choice:")}
_INTS = {"points", "wire"}
_REQUIRED = {"panel", "root_gap", "block_x", "table_y"}


@dataclass
class Side:
    kind: str = "rechteck"
    w: float = 60.0
    h: float = 40.0
    r: float = 8.0
    dx: float = 0.0
    dy: float = 0.0
    hole: str = "keine"
    hole_w: float = 20.0
    hole_h: float = 20.0
    hole_r: float = 0.0


@dataclass
class ShapeSpec:
    panel: float = 200.0
    points: int = 72
    a: Side = None
    b: Side = None
    root_gap: float = 150.0
    block_x: float = 20.0
    table_y: float = 20.0
    chord_y: float | None = None        # never set here; loft() accepts it for legacy wings
    lead: float = 12.0
    feed: float = 200.0
    wire: int = 0
    warmup: float = 3.0
    kerf: float = 1.0
    margin: float = 10.0
    block_s: float | None = None
    block_w: float | None = None
    block_len: float | None = None
    block_y: float | None = None
    block_h: float | None = None
    mirror: bool = False

    def __post_init__(self):
        self.a = self.a or Side()
        self.b = self.b or Side()

    @classmethod
    def parse(cls, text: str) -> "ShapeSpec":
        spec = cls()
        seen = set()
        for n, raw in enumerate(text.splitlines(), start=1):
            line = raw.split(";", 1)[0].split("#", 1)[0].strip()
            if not line or line.startswith("["):
                continue
            if "=" not in line:
                raise WingError(f"Zeile {n}: erwartet 'name = wert': {raw.strip()!r}")
            key, _, value = line.partition("=")
            key, value = key.strip().lower(), value.strip()
            target, attr = spec, key
            if key[:2] in ("a_", "b_"):
                target, attr = getattr(spec, key[0]), key[2:]
            if not hasattr(target, attr):
                raise WingError(f"Zeile {n}: unbekannter Parameter {key!r}")
            if value == "":
                continue
            if key in _CHOICES:
                if value.lower() not in _CHOICES[key]:
                    raise WingError(f"Zeile {n}: {key} muss eines von {', '.join(_CHOICES[key])} sein")
                setattr(target, attr, value.lower())
            else:
                try:
                    num = float(value.replace(",", "."))
                except ValueError:
                    raise WingError(f"Zeile {n}: {key} braucht eine Zahl, nicht {value!r}") from None
                setattr(target, attr, int(num) if key in _INTS else num)
            seen.add(key)
        missing = _REQUIRED - seen
        if missing:
            raise WingError("fehlt: " + ", ".join(sorted(missing)))
        for side, name in ((spec.a, "a"), (spec.b, "b")):
            if side.w <= 0 or side.h <= 0 or side.r < 0:
                raise WingError(f"{name}: Breite und Hoehe > 0, Eckenradius >= 0")
            if side.hole != "keine" and (side.hole_w <= 0 or side.hole_h <= 0 or side.hole_r < 0):
                raise WingError(f"{name}: Lochmasse > 0")
        if (spec.a.hole == "keine") != (spec.b.hole == "keine"):
            raise WingError("Loch: beide Seiten brauchen ein Loch oder keines")
        if spec.points < 12:
            raise WingError("points: mindestens 12")
        if spec.panel <= 0 or spec.feed <= 0:
            raise WingError("panel und feed muessen > 0 sein")
        if spec.lead < 0 or spec.margin < 0:
            raise WingError("lead und margin duerfen nicht negativ sein")
        return spec


# ------------------------------------------------------------ geometry ------
Point = tuple[float, float]


def rounded_polygon(verts: list[Point], r: float, seg: int = 10) -> list[Point]:
    """Convex polygon (CCW) with every corner replaced by an arc of radius r."""
    n = len(verts)
    if r <= 0:
        return list(verts)
    out: list[Point] = []
    for i in range(n):
        p0, p1, p2 = verts[i - 1], verts[i], verts[(i + 1) % n]
        a = (p0[0] - p1[0], p0[1] - p1[1]); b = (p2[0] - p1[0], p2[1] - p1[1])
        la, lb = math.hypot(*a), math.hypot(*b)
        ua, ub = (a[0] / la, a[1] / la), (b[0] / lb, b[1] / lb)
        cos_t = max(-1.0, min(1.0, ua[0] * ub[0] + ua[1] * ub[1]))
        theta = math.acos(cos_t)                      # interior angle
        rr = min(r, 0.499 * min(la, lb) * math.tan(theta / 2))   # never past the edge midpoints
        d = rr / math.tan(theta / 2)                  # tangent point distance from the corner
        t1 = (p1[0] + ua[0] * d, p1[1] + ua[1] * d)
        t2 = (p1[0] + ub[0] * d, p1[1] + ub[1] * d)
        bis = (ua[0] + ub[0], ua[1] + ub[1]); lbis = math.hypot(*bis)
        c = (p1[0] + bis[0] / lbis * rr / math.sin(theta / 2), p1[1] + bis[1] / lbis * rr / math.sin(theta / 2))
        a1, a2 = math.atan2(t1[1] - c[1], t1[0] - c[0]), math.atan2(t2[1] - c[1], t2[0] - c[0])
        while a2 < a1:                                # CCW polygon: the arc runs a1 -> a2 the short way
            a2 += 2 * math.pi
        if a2 - a1 > math.pi:
            a1, a2 = a2 - 2 * math.pi, a1
            pts = [(c[0] + rr * math.cos(a), c[1] + rr * math.sin(a))
                   for a in [a2 - (a2 - a1) * k / seg for k in range(seg + 1)]]
        else:
            pts = [(c[0] + rr * math.cos(a), c[1] + rr * math.sin(a))
                   for a in [a1 + (a2 - a1) * k / seg for k in range(seg + 1)]]
        out.extend(pts)
    return out


def contour(kind: str, w: float, h: float, r: float = 0.0) -> list[Point]:
    """Dense CCW outline of one cross-section, centred on (0, 0)."""
    if kind == "kreis":
        h = w
    if kind in ("kreis", "ellipse"):
        n = 360
        return [(w / 2 * math.cos(2 * math.pi * i / n), h / 2 * math.sin(2 * math.pi * i / n)) for i in range(n)]
    if kind == "rechteck":
        verts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    elif kind == "dreieck":
        verts = [(-w / 2, -h / 2), (w / 2, -h / 2), (0.0, h / 2)]
    else:
        raise WingError(f"unbekannte Form {kind!r}")
    return rounded_polygon(verts, r)


def by_angle(poly: list[Point], n: int) -> list[Point]:
    """n + 1 points of a convex outline around (0, 0) at equal angles, starting
    and ending at the rear (angle pi), CCW. Same n -> point-for-point pairs."""
    m = len(poly)
    out = []
    for i in range(n):
        th = math.pi + 2 * math.pi * i / n
        dx, dy = math.cos(th), math.sin(th)
        best = None
        for k in range(m):
            (x1, y1), (x2, y2) = poly[k], poly[(k + 1) % m]
            ex, ey = x2 - x1, y2 - y1
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            t = (x1 * ey - y1 * ex) / den          # distance along the ray
            u = (x1 * dy - y1 * dx) / den          # position along the edge
            if t > 0 and -1e-9 <= u <= 1 + 1e-9 and (best is None or t < best):
                best = t
        if best is None:
            raise WingError("Form umschliesst ihren Mittelpunkt nicht")
        out.append((best * dx, best * dy))
    out.append(out[0])
    return out


def side_path(side: Side, n: int, kerf: float) -> list[Point]:
    """One side's wire path relative to its centre: outer loop, and for a ring
    the slit to the hole, the hole loop and the slit back."""
    outer = af.offset_loop(by_angle(contour(side.kind, side.w, side.h, side.r), n), kerf / 2.0)
    if side.hole == "keine":
        return outer
    hole = af.offset_loop(by_angle(contour(side.hole, side.hole_w, side.hole_h, side.hole_r), n), -kerf / 2.0)
    return outer + hole + [outer[0]]


def build_path(spec: ShapeSpec, machine: Machine) -> WingPath:
    a = side_path(spec.a, spec.points, spec.kerf)
    b = [(x + spec.b.dx, y + spec.b.dy) for x, y in side_path(spec.b, spec.points, spec.kerf)]
    rear = min(min(x for x, _ in a), min(x for x, _ in b))
    shift = spec.block_x + spec.lead - rear             # rearmost point sits `lead` past the block face
    a = [(x + shift, y) for x, y in a]
    b = [(x + shift, y) for x, y in b]
    path = loft(spec, a, b, machine)
    desc = lambda s: f"{s.kind} {s.w:g}x{s.h:g}" + (f" Loch {s.hole} {s.hole_w:g}x{s.hole_h:g}" if s.hole != "keine" else "")
    path.notes.insert(1, f"Form: A {desc(spec.a)} -> B {desc(spec.b)}, Laenge {spec.panel:g}")
    # sides of different size: the wire lines converge and cross somewhere
    # beyond the smaller side; at a tower past that point the contour is inverted
    n = spec.points + 1
    for tower, pts in ((1, path.tower1), (2, path.tower2)):
        if _signed_area(pts[:n]) <= 0:
            path.notes.append(f"Drahtlinien kreuzen sich vor Turm {tower} - dort darf kein Schaum liegen")
    return path


def _signed_area(loop: list[Point]) -> float:
    return 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(loop, loop[1:]))


def generate(spec: ShapeSpec, machine: Machine, airfoil_dir: Path | None = None) -> tuple[str, WingPath]:
    path = build_path(spec, machine)
    header = ["; foamcut shape: " + path.notes[1][6:], f"; Kerf {spec.kerf:g}, Vorschub {spec.feed:g} mm/min"]
    return emit_gcode(path, spec.feed, spec.wire, spec.warmup, header), path


def shape_name(spec: ShapeSpec) -> str:
    ring = "_ring" if spec.a.hole != "keine" else ""
    return f"{spec.a.kind}_{spec.a.w:g}x{spec.a.h:g}-{spec.b.kind}_{spec.b.w:g}x{spec.b.h:g}_{spec.panel:g}{ring}.nc"


def shape_to_text(values: dict[str, str]) -> str:
    return to_text(values, FIELDS, "; foamcut shape")


def shape_from_text(text: str) -> dict[str, str]:
    return from_text(text, FIELDS)


SHAPE_MODEL = Model("Formen", "shape", FIELDS, ShapeSpec.parse, generate, shape_name, shape_to_text,
                    shape_from_text, TEMPLATE, "shape (*.shape);;alle (*)")
