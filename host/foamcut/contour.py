"""Free 2D outlines from an SVG (letters, silhouettes, sketches), cut
prismatically: both towers follow the same contour, so the block thickness
does not matter (parallel cut, X=U / Y=V).

What the wire needs beyond the drawing, all done here:
- kerf: outer outlines run kerf/2 outside, holes kerf/2 inside;
- no plunging: a hole is reached through a slit from its rearmost point
  straight back to the enclosing outline (or a sibling hole in the way);
- several outlines in one drawing are cut one after another, the wire
  travelling through the waste around the convex hulls of the others - it
  never crosses a piece that is already cut free;
- entry from the block's back face to the rearmost outline, exit the same way.

Coordinates: SVG x -> machine X (forward), SVG y up -> machine Y (up); so
the drawing is seen from the side of tower 1 as drawn. `mirror` flips it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from . import geom
from .machine import Machine
from .svg import SvgError, load_svg
from .wing import (Model, WingError, WingPath, _template, emit_gcode, field_catalogue, from_text, loft, to_text)

Point = tuple[float, float]
CLEARANCE = 1.5         # mm between the travel channel and a cut piece's channel


def clearance(kerf: float) -> float:
    """Distance the travel path keeps from a piece's cut path: twice the kerf
    (Valentin, 2026-09-23: "Draht darf an geschnittenen Teilen schon nah
    fahren - 2x Schnittbreite"), never under 1.5 mm."""
    return max(2 * kerf, CLEARANCE)

FIELDS = [
    ("zeichnung", "Zeichnung", [
        ("svg", "SVG-Datei", "", "",
         "Zeichnung mit geschlossenen Konturen (Inkscape: Text vorher in Pfade umwandeln). "
         "Aeussere Konturen werden Teile, Konturen darin Loecher.", "file:svg"),
        ("width", "Breite", "mm", "",
         "Gesamtbreite der Zeichnung in X nach dem Skalieren. Leer = Masse aus der Datei mal Faktor.", "num"),
        ("scale", "Faktor", "", "1",
         "Skalierung der Zeichnung, wenn keine Breite angegeben ist.", "num"),
        ("mirror", "Spiegeln", "ja/nein", "nein",
         "Zeichnung in X spiegeln (fuer das Gegenstueck oder weil die Vorlage seitenverkehrt ist).", "bool"),
        ("panel", "Dicke", "mm", "30",
         "Blockdicke in Spannrichtung, von Seite A (am Turm mit festem Draht) nach B. "
         "Beide Seiten sind gleich; die Dicke bestimmt nur Block und Schnittzeit.", "num"),
        ("step", "Aufloesung", "mm", "0.5",
         "Laengster Abschnitt, in den Kurven zerlegt werden. Kleiner = runder, mehr Zeilen.", "num"),
    ]),
    ("lage", "Lage im Schneider", [
        ("root_gap", "Seite A ab Turm", "mm", "150",
         "Abstand der Seite A des Blocks vom Turm mit dem festen Draht, entlang des Drahts.", "num"),
        ("block_x", "Block Rueckseite X", "mm", "20",
         "Abstand der Blockrueckseite vom Referenzpunkt nach vorn. Dort taucht der Draht ein.", "num"),
        ("table_y", "Tischoberkante Y", "mm", "20",
         "Hoehe der Tischoberkante (= Blockunterkante) ueber dem Draht-Null. Die Zeichnung liegt 'Rand' darueber.", "num"),
        ("lead", "Einlauf", "mm", "12",
         "Strecke im Schaum von der Blockrueckseite bis zum hintersten Punkt der Zeichnung.", "num"),
    ]),
    ("schnitt", "Schnitt", [
        ("margin", "Rand", "mm", "10",
         "Mindestabstand der Zeichnung zu Vorderseite, Ober-, Unterseite und Seite B des Blocks.", "num"),
        ("tab", "Haltesteg", "mm", "0",
         "So viel jeder Kontur bleibt ungeschnitten (am hintersten Punkt), damit Teil und Lochkern nicht "
         "auf den Draht fallen; danach von Hand brechen. 0 = durchschneiden.", "num"),
    ]),
    ("block", "Block", [
        ("block_s", "Block Anfang ab Seite A", "mm", "", "0 oder leer = der Block beginnt an Seite A.", "num"),
        ("block_w", "Block Breite", "mm", "", "Ausdehnung in Spannrichtung. Leer = Dicke plus Rand.", "num"),
        ("block_len", "Block Laenge", "mm", "", "Leer = Mindestblock.", "num"),
        ("block_h", "Block Hoehe", "mm", "", "Ab Tischoberkante. Leer = Mindestblock.", "num"),
    ]),
]

TEMPLATE = _template(FIELDS, ("; Freie Kontur aus einer SVG-Zeichnung, beide Seiten gleich (Parallelschnitt).",
                              "; Alle Masse in mm. Zeilen mit ; sind Kommentare."))
_NUMERIC = {"width", "scale", "panel", "step", "root_gap", "block_x", "table_y", "lead", "margin", "tab",
            "block_s", "block_w", "block_len", "block_h"}
_MACHINE_KEYS = {"kerf", "feed", "wire", "warmup"}
_REQUIRED = {"svg", "panel", "root_gap", "block_x", "table_y"}
_BOOL = {"ja": True, "nein": False, "yes": True, "no": False, "true": True, "false": False, "1": True, "0": False}


@dataclass
class ContourSpec:
    svg: str = ""
    width: float | None = None
    scale: float = 1.0
    mirror: bool = False
    panel: float = 30.0
    step: float = 0.5
    root_gap: float = 150.0
    block_x: float = 20.0
    table_y: float = 20.0
    chord_y: float | None = None
    lead: float = 12.0
    margin: float = 10.0
    tab: float = 0.0
    block_s: float | None = None
    block_w: float | None = None
    block_len: float | None = None
    block_y: float | None = None
    block_h: float | None = None

    @classmethod
    def parse(cls, text: str) -> "ContourSpec":
        spec = cls()
        seen = set()
        for n, raw in enumerate(text.splitlines(), start=1):
            line = raw.split(";", 1)[0].strip()
            if not line or line.startswith("["):
                continue
            if "=" not in line:
                raise WingError(f"Zeile {n}: erwartet 'name = wert': {raw.strip()!r}")
            key, _, value = line.partition("=")
            key, value = key.strip().lower(), value.strip()
            if key in _MACHINE_KEYS:
                continue
            if not hasattr(spec, key):
                raise WingError(f"Zeile {n}: unbekannter Parameter {key!r}")
            if value == "":
                continue
            if key == "mirror":
                if value.lower() not in _BOOL:
                    raise WingError(f"Zeile {n}: mirror muss ja oder nein sein")
                spec.mirror = _BOOL[value.lower()]
            elif key in _NUMERIC:
                try:
                    setattr(spec, key, float(value.replace(",", ".")))
                except ValueError:
                    raise WingError(f"Zeile {n}: {key} braucht eine Zahl, nicht {value!r}") from None
            else:
                setattr(spec, key, value)
            seen.add(key)
        missing = _REQUIRED - seen
        if missing:
            raise WingError("fehlt: " + ", ".join(sorted(missing)))
        if spec.panel <= 0 or spec.scale <= 0 or spec.step <= 0:
            raise WingError("panel, scale und step muessen > 0 sein")
        if spec.width is not None and spec.width <= 0:
            raise WingError("width muss > 0 sein (oder leer)")
        if spec.lead < 0 or spec.margin < 0 or spec.tab < 0:
            raise WingError("lead, margin und tab duerfen nicht negativ sein")
        return spec


# ------------------------------------------------------------- planning ---
@dataclass
class Outline:
    loop: list[Point]               # CCW, kerf applied
    holes: list["Outline"]
    rear: int = 0                   # index of the rearmost vertex


def _offset(loop: list[Point], d: float) -> list[Point]:
    """Kerf offset with proper corners (miter), unlike the airfoil offset that
    is tuned for dense smooth loops."""
    return geom.grow(loop, d) if abs(d) > 1e-12 else list(loop)


def classify(loops: list[list[Point]], kerf: float) -> list[Outline]:
    """Outer outlines with their holes (nesting by containment), kerf applied."""
    loops = [geom.ccw(geom.dedupe(l)) for l in loops]
    loops = [l for l in loops if len(l) > 2 and abs(geom.signed_area(l)) > 1e-6]
    if not loops:
        raise WingError("keine brauchbare Kontur in der Zeichnung")
    areas = [abs(geom.signed_area(l)) for l in loops]
    parents: list[int | None] = []
    depth: list[int] = []
    for i, l in enumerate(loops):
        containers = [j for j, other in enumerate(loops) if j != i and areas[j] > areas[i] and geom.inside(l[0], other)]
        depth.append(len(containers))
        parents.append(min(containers, key=lambda j: areas[j]) if containers else None)
    outlines: dict[int, Outline] = {}
    for i, l in enumerate(loops):
        if depth[i] % 2 == 0:
            outlines[i] = Outline(_offset(l, kerf / 2.0), [])
    for i, l in enumerate(loops):
        if depth[i] % 2 == 1:
            outlines[parents[i]].holes.append(Outline(_offset(l, -kerf / 2.0), []))
        elif depth[i] >= 2:
            pass                                    # island inside a hole: its own part, fine
    for o in outlines.values():
        o.rear = min(range(len(o.loop)), key=lambda k: o.loop[k][0])
        for h in o.holes:
            h.rear = min(range(len(h.loop)), key=lambda k: h.loop[k][0])
    return sorted(outlines.values(), key=lambda o: o.loop[o.rear][0])


def trim_tail(pts: list[Point], tab: float) -> list[Point]:
    """Drop the last `tab` mm of a closed walk (pts[-1] == pts[0]) so a bridge
    of foam stays and the piece does not drop onto the wire."""
    if tab <= 0 or len(pts) < 3:
        return pts
    left = tab
    out = list(pts)
    while len(out) > 2:
        d = math.dist(out[-2], out[-1])
        if d > left:
            f = (d - left) / d
            a, b = out[-2], out[-1]
            out[-1] = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            return out
        left -= d
        out.pop()
    return out


def _cut_outline(o: Outline, tab: float = 0.0) -> list[Point]:
    """One outline with its holes as a single wire path from its rearmost
    vertex around and back: holes hang off slits that run straight back.
    `tab` > 0 leaves that much of every loop uncut (Haltesteg)."""
    # attach every hole to the first loop its backward ray hits (the outline
    # or a hole nearer the back), so slits never cross a hole
    hosts: list[Outline] = [o]
    junctions: dict[int, list[tuple[int, Outline, Point]]] = {}      # id(host) -> [(edge, hole, point)]
    for h in sorted(o.holes, key=lambda h: h.loop[h.rear][0]):
        origin = h.loop[h.rear]
        best = None
        for host in hosts:
            hit = geom.ray_hit(origin, (-1.0, 0.0), host.loop)
            if hit and (best is None or hit[0] < best[0][0]):
                best = (hit, host)
        if best is None:
            raise WingError("Loch ohne Weg nach hinten - Zeichnung pruefen")
        (dist, edge), host = best
        junctions.setdefault(id(host), []).append((edge, h, (origin[0] - dist, origin[1])))
        hosts.append(h)

    def walk(loop_o: Outline, start: int) -> list[Point]:
        loop = loop_o.loop
        n = len(loop)
        js = junctions.get(id(loop_o), [])
        out: list[Point] = []
        for k in range(n + 1):
            i = (start + k) % n
            out.append(loop[i])
            if k == n:
                break
            # junctions on edge i -> i+1, nearest to vertex i first
            for edge, hole, jp in sorted((j for j in js if j[0] == i), key=lambda j: math.dist(loop[i], j[2])):
                out.append(jp)
                out.extend(walk(hole, hole.rear))
                out.append(jp)
        return trim_tail(out, tab)
    return walk(o, o.rear)


@dataclass
class Part:
    """One piece to cut: its wire path on side A and B (same length, both
    starting and ending at the piece's rearmost point), and the convex hull
    the wire must travel around once the piece is cut."""
    a: list[Point]
    b: list[Point]
    hull: list[Point]
    label: str = ""

    @property
    def port(self) -> Point:
        """Where the wire waits before entering / after leaving: the rearmost
        vertex of the piece's own hull, so travel legs start and end on hull
        boundaries and never inside another hull (the packing keeps hulls apart)."""
        return min(self.hull, key=lambda q: (q[0], abs(q[1] - self.a[0][1])))


def part_from_outline(o: Outline, tab: float = 0.0, label: str = "", kerf: float = 0.0) -> Part:
    path = _cut_outline(o, tab)
    return Part(path, list(path), geom.grow(geom.convex_hull(o.loop), clearance(kerf)), label)


def route_parts(parts: list[Part], entry: Point) -> tuple[list[Point], list[Point], list[int]]:
    """Cut all parts one after another from the entry point and back to it:
    nearest port first, travelling around every other part's hull. Returns
    the side A path, the side B path (same length: the travel points are
    shared, only the pieces differ) and the cut order."""
    pa: list[Point] = []; pb: list[Point] = []
    pos = entry
    todo = list(range(len(parts)))
    order: list[int] = []
    while todo:
        k = min(todo, key=lambda k: math.dist(pos, parts[k].port))
        todo.remove(k); order.append(k)
        part = parts[k]
        # every hull is an obstacle, the target's too: the wire must not cross
        # a piece before cutting it any more than after
        obstacles = [q.hull for q in parts]
        leg = geom.route(pos, part.port, obstacles)
        leg = leg[1:] if pa else leg
        pa.extend(leg); pb.extend(leg)
        pa.extend(part.a); pb.extend(part.b)
        pa.append(part.port); pb.append(part.port)
        pos = part.port
    leg = geom.route(pos, entry, [q.hull for q in parts])
    pa.extend(leg[1:]); pb.extend(leg[1:])
    return pa, pb, order


def plan(loops: list[list[Point]], kerf: float, entry_x: float, tab: float = 0.0) -> tuple[list[Point], list[str]]:
    """All outlines as one path from the entry point (entry_x, y of the
    rearmost outline) and back to it, in the drawing's coordinates."""
    outlines = classify(loops, kerf)
    parts = [part_from_outline(o, tab, kerf=kerf) for o in outlines]
    entry = (entry_x, outlines[0].loop[outlines[0].rear][1])
    path, _, order = route_parts(parts, entry)
    notes = [f"{len(outlines)} Teil(e), {sum(len(o.holes) for o in outlines)} Loch/Loecher, "
             f"Reihenfolge von hinten: " + ", ".join(str(k + 1) for k in order)
             + (f"; Haltesteg {tab:g} mm an jeder Kontur (von Hand brechen)" if tab > 0 else "")]
    return path, notes


# ---------------------------------------------------------------- build ---
def _drawing(spec: ContourSpec) -> tuple[list[list[Point]], list[str]]:
    p = Path(spec.svg).expanduser()
    if not p.exists():
        raise WingError(f"SVG-Datei nicht gefunden: {spec.svg}")
    try:
        loops, warnings = load_svg(p, spec.step)
    except SvgError as e:
        raise WingError(str(e)) from None
    xs = [q[0] for l in loops for q in l]
    x0, x1 = min(xs), max(xs)
    f = spec.width / (x1 - x0) if spec.width else spec.scale
    loops = [[(x * f, y * f) for x, y in l] for l in loops]
    if spec.mirror:
        loops = [[(-x, y) for x, y in l] for l in loops]
    return loops, warnings


def build_path(spec: ContourSpec, machine: Machine) -> WingPath:
    loops, warnings = _drawing(spec)
    rear = min(q[0] for l in loops for q in l)
    shift_x = spec.block_x + spec.lead - rear
    loops = [[(x + shift_x, y) for x, y in l] for l in loops]
    path, notes = plan(loops, machine.kerf_mm, spec.block_x, spec.tab)
    y0 = path[0][1]
    rel = [(x, y - y0) for x, y in path]             # entry line = reference line (y = 0)
    wp = loft(spec, rel, list(rel), machine)
    xs = [q[0] for l in loops for q in l]; ys = [q[1] for l in loops for q in l]
    wp.notes.insert(1, f"Kontur: {Path(spec.svg).name}, {max(xs) - min(xs):.1f} x {max(ys) - min(ys):.1f} mm"
                       + (", gespiegelt" if spec.mirror else "") + f", Dicke {spec.panel:g}")
    wp.notes.extend(notes)
    wp.notes.extend(warnings)
    return wp


def generate(spec: ContourSpec, machine: Machine, airfoil_dir: Path | None = None) -> tuple[str, WingPath]:
    path = build_path(spec, machine)
    header = ["; foamcut contour: " + path.notes[1][8:],
              f"; Kerf {machine.kerf_mm:g}, Vorschub {machine.cut_feed:g} mm/min, Parallelschnitt X=U Y=V"]
    return emit_gcode(path, machine.cut_feed, machine.wire_power, machine.warmup_s, header), path


def contour_name(spec: ContourSpec) -> str:
    stem = Path(spec.svg).stem or "kontur"
    size = f"_b{spec.width:g}" if spec.width else (f"_x{spec.scale:g}" if spec.scale != 1 else "")
    return f"{stem}{size}{'_sp' if spec.mirror else ''}_{spec.panel:g}.nc"


def contour_to_text(values: dict[str, str]) -> str:
    return to_text(values, FIELDS, "; foamcut contour")


def contour_from_text(text: str) -> dict[str, str]:
    return from_text(text, FIELDS)


def preview(spec: ContourSpec):
    """Outlines of the drawing in mm plus the indices of the holes."""
    loops, _ = _drawing(spec)
    # a loop is a hole when it lies inside larger loops an odd number of times
    holes = set()
    areas = [abs(geom.signed_area(l)) for l in loops]
    for i, l in enumerate(loops):
        depth = sum(1 for j, o in enumerate(loops) if j != i and areas[j] > areas[i] and geom.inside(l[0], o))
        if depth % 2 == 1:
            holes.add(i)
    return loops, holes


CONTOUR_MODEL = Model("Kontur", "contour", FIELDS, ContourSpec.parse, generate, contour_name, contour_to_text,
                      contour_from_text, TEMPLATE, "contour (*.contour);;alle (*)", preview, "loops")
