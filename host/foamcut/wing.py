"""Wing panel generator: root + tip airfoil -> one-pass XYUV G-code.

Geometry, in machine coordinates:
  X  along the chord, positive toward the front; the reference (0) is at
     the back, so the trailing edge points at the reference and the leading
     edge points forward.
  Y  up.
  s  span, from tower 1 (s = 0) to tower 2 (s = tower_gap). Not an axis:
     the wire is a straight line between the two carriages, so a point on
     the root profile and its partner on the tip profile define the line,
     and the carriage positions are that line extrapolated to s = 0 and
     s = tower_gap.

The spec is plain text, `key = value` per line, see TEMPLATE.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from . import AXES
from . import airfoil as af
from .machine import Machine

# (key, label, unit, default, help) - the one place parameters are described.
# kind: "num" numeric, "int" integer, "airfoil" file name, "bool" ja/nein
FIELDS = [
    ("profil", "Profil", [
        ("root_airfoil", "Profil an der Wurzel", "", "clarky.dat",
         "Profildatei (.dat) fuer die Rumpfseite. Liegt in airfoil/.", "airfoil"),
        ("root_chord", "Wurzeltiefe", "mm", "100",
         "Profiltiefe (Sehnenlaenge) an der Wurzel, Nasenleiste bis Hinterkante.", "num"),
        ("tip_airfoil", "Profil am Ende", "", "",
         "Profildatei fuer das aeussere Ende. Leer = gleiches Profil wie an der Wurzel.", "airfoil"),
        ("tip_chord", "Endtiefe", "mm", "80",
         "Profiltiefe am aeusseren Ende. Gleich der Wurzeltiefe = Rechteckfluegel.", "num"),
        ("panel", "Panellaenge", "mm", "400",
         "Laenge des Stuecks von Wurzel bis Ende (Halbspannweite bei einem Fluegel je Seite).", "num"),
        ("area", "Flaeche", "dm²", "",
         "Flaeche dieses Panels (bei zwei gleichen Haelften die halbe Fluegelflaeche). Leer = Tiefen wie "
         "eingegeben. Sonst werden Wurzel- und Endtiefe aus Flaeche, Panellaenge und Zuspitzung berechnet: "
         "Wurzeltiefe = 2*Flaeche / (Panel * (1 + Zuspitzung)).", "num"),
        ("taper", "Zuspitzung", "", "1",
         "Endtiefe / Wurzeltiefe fuer die Berechnung aus der Flaeche. 1 = Rechteck, 0.5..0.7 = Trapez.", "num"),
        ("sweep", "Pfeilung", "mm", "0",
         "Um so viel liegt die Nasenleiste am Ende weiter hinten als an der Wurzel. 0 = gerade Nasenleiste.", "num"),
        ("washout", "Schraenkung", "Grad", "0",
         "Verdrehung des Endprofils um seine Viertelsehne. Positiv = Nase am Ende nach unten.", "num"),
        ("dihedral", "V-Form", "Grad", "0",
         "Anstellung dieses Panels gegen die Waagerechte (je Seite). Der Draht kann die schraege "
         "Wurzelflaeche nicht schneiden (er laeuft zwischen den Tuermen fast waagerecht, die Flaeche steht "
         "fast senkrecht) - das Panel wird gerade geschnitten, der Winkel kommt in den Verbinder oder wird "
         "als Keil an der Wurzelkante geschliffen; die Masse dafuer stehen im Ergebnis.", "num"),
        ("mirror", "Spiegelverkehrt", "", "nein",
         "Die Wurzel liegt immer am Turm mit dem fest eingespannten Draht (Maschine: 'Draht fest an Turm'), "
         "das Ende zeigt zum Turm mit dem Gewicht. Fuer den gegenueberliegenden Fluegel 'ja' waehlen: "
         "das Profil wird kopfueber geschnitten, das fertige Teil um seine Sehnenachse gedreht ergibt "
         "das Spiegelbild. Bei Rechteckfluegeln ohne Schraenkung unnoetig.", "bool"),
    ]),
    ("ruder", "Ruder", [
        ("aileron", "Rudertiefe", "% der Tiefe", "0",
         "Tiefe des Ruders (Querruder/Klappe) ab Hinterkante in Prozent der Profiltiefe. 0 = kein "
         "Ruderschnitt. Sonst faehrt der Draht nach dem Profil im Kanal der Unterseite zur Scharnierlinie "
         "zurueck und schneidet von unten bis unter die Oberseite; die Oberseite bleibt als Scharnierhaut "
         "stehen. Der Schnitt laeuft ueber die ganze Blockbreite (Draht), das Ruder wird in Spannrichtung "
         "danach mit dem Messer abgelaengt.", "num"),
        ("hinge_skin", "Scharnierhaut", "mm", "1.5",
         "So viel Schaum bleibt an der Oberseite stehen (Folienscharnier).", "num"),
        ("hinge_v", "Kerbe unten", "mm", "0",
         "Breite der V-Kerbe an der Unterseite, damit das Ruder nach unten ausschlagen kann. "
         "0 = gerader Schlitz (nur Schnittbreite).", "num"),
    ]),
    ("lage", "Lage im Schneider", [
        ("root_gap", "Wurzelebene ab Turm", "mm", "150",
         "Abstand der Wurzelseite des Blocks vom Turm mit dem festen Draht, entlang des Drahts. "
         "Schiene und Aufbau geben vor, wie nah der Block an den Turm kann.", "num"),
        ("block_x", "Block Rueckseite X", "mm", "20",
         "Abstand der Blockrueckseite (Hinterkantenseite) vom Referenzpunkt nach vorn. Dort taucht der "
         "Draht ein. So gross, dass der geparkte heisse Draht den Block nicht anschmilzt. "
         "Die Nasenleiste zeigt nach vorn.", "num"),
        ("table_y", "Tischoberkante Y", "mm", "20",
         "Hoehe der Tischoberkante (= Blockunterkante) ueber dem Draht-Null. Das Profil liegt 'Rand' "
         "darueber; die Sehnenhoehe folgt daraus. Der Block-Schritt nennt den moeglichen Bereich "
         "(Verfahrweg) und wie weit der Tisch reichen darf.", "num"),
        ("lead", "Einlauf", "mm", "12",
         "Strecke im Schaum von der Blockrueckseite bis zur Hinterkante: der Draht schneidet sich gerade "
         "ein, bevor das Profil beginnt, und laeuft dort wieder aus. Verschiebt das Profil im Block, "
         "nicht den Block.", "num"),
    ]),
    ("schnitt", "Schnitt", [
        ("points", "Stuetzpunkte je Seite", "", "60",
         "Punkte je Profilseite (oben/unten). Mehr = glatter, mehr G-Code-Zeilen.", "int"),
        ("margin", "Rand", "mm", "10",
         "Mindestabstand des Profils zu Vorderseite, Ober-, Unterseite und Endseite des Blocks. "
         "Nicht zur Wurzelseite (dort liegt die Wurzel) und nicht zur Rueckseite (dort gilt der Einlauf). "
         "Daraus folgt der Mindestblock.", "num"),
    ]),
    ("block", "Block", [
        ("block_s", "Block Anfang ab Wurzel", "mm", "",
         "Abstand der wurzelseitigen Blockflaeche von der Wurzelebene, in Spannrichtung. "
         "0 oder leer = der Block beginnt an der Wurzel.", "num"),
        ("block_w", "Block Breite", "mm", "",
         "Ausdehnung des Blocks in Spannrichtung. Leer = Panel plus Rand.", "num"),
        ("block_len", "Block Laenge", "mm", "", "Leer = Mindestblock (Profil plus Rand).", "num"),
        ("block_h", "Block Hoehe", "mm", "", "Ab Tischoberkante (der Block liegt auf dem Tisch). Leer = Mindestblock.", "num"),
    ]),
]


def field_catalogue(fields=None) -> dict[str, tuple]:
    return {key: (label, unit, default, help_, kind)
            for _, _, group in (fields or FIELDS) for key, label, unit, default, help_, kind in group}


def _template(fields=None, head: tuple[str, ...] = ("; Fluegel-Panel fuer den Schaumschneider. Alle Masse in mm.",
                                                    "; Zeilen mit ; sind Kommentare. Profildateien liegen in airfoil/.")) -> str:
    out = list(head) + [""]
    for section, title, group in (fields or FIELDS):
        out.append(f"[{section}]  ; {title}")
        for key, label, unit, default, help_, kind in group:
            u = f" [{unit}]" if unit else ""
            out.append(f"{key:<12} = {default:<12} ; {label}{u}: {help_}")
        out.append("")
    return "\n".join(out)


def to_text(values: dict[str, str], fields=None, head: str = "; foamcut wing") -> str:
    """Form values -> the .wing text format (the serialisation, and what parse() reads)."""
    out = [head, ""]
    for section, title, group in (fields or FIELDS):
        out.append(f"[{section}]")
        for key, label, unit, default, help_, kind in group:
            out.append(f"{key} = {values.get(key, '')}")
        out.append("")
    return "\n".join(out)


def from_text(text: str, fields=None) -> dict[str, str]:
    """.wing text -> raw form values (strings), unknown keys ignored."""
    values = {key: default for key, (_, _, default, _, _) in field_catalogue(fields).items()}
    legacy_te_x = None
    seen_block_x = False
    values_seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].split("#", 1)[0].strip()
        if "=" in line and not line.startswith("["):
            key, _, value = line.partition("=")
            key, value = key.strip().lower(), value.strip()
            if key == "side" and value:
                key, value = "mirror", legacy_side_to_mirror(value)
            if key == "te_x" and value:
                legacy_te_x = value
                continue
            if key == "chord_y":
                continue                      # legacy; WingPage.load_spec converts it to table_y
            if key == "block_y":
                if value and "table_y" not in values_seen:
                    values["table_y"] = value
                continue
            if key == "block_x" and value:
                seen_block_x = True
            if key in values:
                values[key] = value
                if value:
                    values_seen.add(key)
    if legacy_te_x is not None and not seen_block_x:
        try:
            lead = float((values.get("lead") or "0").replace(",", "."))
            values["block_x"] = f"{float(legacy_te_x.replace(',', '.')) - lead:g}"
        except ValueError:
            values["block_x"] = legacy_te_x
    return values


TEMPLATE = _template()

_NUMERIC = {
    "root_chord", "tip_chord", "panel", "area", "taper", "sweep", "washout", "dihedral", "root_gap", "block_x", "te_x",
    "table_y", "chord_y", "lead", "block_s", "block_w", "block_len", "block_y", "block_h",
    "points", "margin", "aileron", "hinge_skin", "hinge_v",
}
_MACHINE_KEYS = {"kerf", "feed", "wire", "warmup"}     # accepted in old files, ignored
_REQUIRED = {"root_airfoil", "root_chord", "panel", "root_gap", "block_x"}

# The table may come no closer than this to the wire (Y, mm) ...
TABLE_CLEARANCE = 2.0
# ... and its rear edge no closer than this to the parked wire at X=0 (mm).
TABLE_REST_CLEARANCE = 5.0
_BOOL = {"ja": True, "nein": False, "yes": True, "no": False, "true": True, "false": False, "1": True, "0": False}


def chords_from_area(area_dm2: float, panel: float, taper: float) -> tuple[float, float]:
    """Trapezoid of the given area (dm²) over the panel length: root and tip chord (mm)."""
    c_root = 2.0 * area_dm2 * 1e4 / (panel * (1.0 + taper))
    return c_root, taper * c_root


def legacy_side_to_mirror(value: str) -> str:
    """Pre-2026-09 files said `side = links|rechts`; rechts meant root at tower 2,
    which is the fixed-wire tower on this machine, i.e. not mirrored."""
    v = value.strip().lower()
    if v in ("rechts", "right"):
        return "nein"
    if v in ("links", "left"):
        return "ja"
    raise WingError(f"side muss links oder rechts sein, nicht {value!r}")


class WingError(ValueError):
    pass


@dataclass
class WingSpec:
    root_airfoil: str = ""
    root_chord: float = 0.0
    tip_airfoil: str = ""
    tip_chord: float | None = None
    panel: float = 0.0
    area: float | None = None           # dm²; given -> chords follow from panel and taper
    taper: float = 1.0
    sweep: float = 0.0
    washout: float = 0.0
    dihedral: float = 0.0               # per panel, degrees; informational - see FIELDS
    mirror: bool = False
    root_gap: float = 0.0
    block_x: float = 0.0
    table_y: float = 20.0
    lead: float = 12.0
    te_x: float | None = None           # pre-2026-09 files placed the trailing edge instead of the block
    chord_y: float | None = None        # ... and the chord height instead of the table; wins if given
    block_s: float | None = None
    block_w: float | None = None
    block_len: float | None = None
    block_y: float | None = None        # legacy input: the block bottom used to be free, now it is the table
    block_h: float | None = None
    points: int = 60
    margin: float = 10.0
    aileron: float = 0.0                # % of chord, 0 = no hinge cut
    hinge_skin: float = 1.5
    hinge_v: float = 0.0

    @classmethod
    def parse(cls, text: str) -> "WingSpec":
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
            if key == "side":                       # old files: rechts = Wurzel an Turm 2
                key, value = "mirror", legacy_side_to_mirror(value)
            if key in _MACHINE_KEYS:                # old files: these live in machine.json now
                continue
            if not hasattr(spec, key):
                raise WingError(f"Zeile {n}: unbekannter Parameter {key!r}")
            if value == "":
                continue
            if key == "mirror":
                if value.lower() not in _BOOL:
                    raise WingError(f"Zeile {n}: mirror muss ja oder nein sein, nicht {value!r}")
                spec.mirror = _BOOL[value.lower()]
            elif key in _NUMERIC:
                try:
                    num = float(value.replace(",", "."))
                except ValueError:
                    raise WingError(f"Zeile {n}: {key} braucht eine Zahl, nicht {value!r}") from None
                setattr(spec, key, int(num) if key == "points" else num)
            else:
                setattr(spec, key, value)
            seen.add(key)
        if spec.te_x is not None and "block_x" not in seen:
            spec.block_x = spec.te_x - spec.lead      # same cut as the old file: block face lead behind the TE
            seen.add("block_x")
        if spec.block_y is not None and "table_y" not in seen and spec.chord_y is None:
            spec.table_y = spec.block_y           # old file: block bottom = table
            seen.add("table_y")
        if spec.chord_y is None and "table_y" not in seen:
            raise WingError("fehlt: table_y")
        missing = _REQUIRED - seen
        if missing:
            raise WingError("fehlt: " + ", ".join(sorted(missing)))
        if spec.area is not None:
            if spec.area <= 0 or spec.taper <= 0 or spec.panel <= 0:
                raise WingError("area, taper und panel muessen > 0 sein")
            spec.root_chord, spec.tip_chord = chords_from_area(spec.area, spec.panel, spec.taper)
        if spec.tip_chord is None:
            spec.tip_chord = spec.root_chord
        if not spec.tip_airfoil:
            spec.tip_airfoil = spec.root_airfoil
        if spec.points < 8:
            raise WingError("points: mindestens 8")
        for k in ("root_chord", "tip_chord", "panel"):
            if getattr(spec, k) <= 0:
                raise WingError(f"{k} muss > 0 sein")
        if spec.lead < 0 or spec.margin < 0:
            raise WingError("lead und margin duerfen nicht negativ sein")
        if not 0 <= spec.aileron < 100 or spec.hinge_skin < 0 or spec.hinge_v < 0:
            raise WingError("aileron 0..99 %, hinge_skin und hinge_v nicht negativ")
        return spec


# ------------------------------------------------------------ geometry ------
Point = tuple[float, float]


def _y_at(pts: list[Point], x: float) -> float:
    """Linear interpolation of y at x along a polyline (x need not be monotonic)."""
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        if (xa - x) * (xb - x) <= 0 and xa != xb:
            return ya + (yb - ya) * (x - xa) / (xb - xa)
    return min(pts, key=lambda q: abs(q[0] - x))[1]


AILERON_STEPS = 6        # points along the lower-surface channel to and from the hinge


def _profile_mm(loop_dat: list[Point], chord: float, te_x: float, chord_y: float,
                twist_deg: float, kerf: float, aileron: tuple[float, float, float] | None = None) -> list[Point]:
    """Airfoil loop (chord 1, x from LE) -> machine XY at the given chord.

    `aileron` = (percent of chord, skin mm, v-notch width mm) appends the hinge
    cut: back along the already cut lower channel to the hinge line, up to
    `skin` below the upper surface, down again and back to the trailing edge.
    """
    # local frame: x from LE toward TE, y up, in mm - standard orientation
    local = [(x * chord, y * chord) for x, y in loop_dat]
    local = af.offset_loop(local, kerf / 2.0)
    if aileron and aileron[0] > 0:
        pct, skin, v = aileron
        n = (len(local) + 1) // 2
        upper, lower = local[:n], local[n - 1:]              # TE->LE, LE->TE
        x_h = chord * (1.0 - pct / 100.0)
        x_te = local[-1][0]
        x1, x2 = min(x_h + v / 2.0, x_te), x_h - v / 2.0     # x1 nearer the TE
        apex = (x_h, _y_at(upper, x_h) - kerf - skin)         # true skin = wire path - kerf/2 each side
        fwd = [(x, _y_at(lower, x)) for x in _linspace(x_te, x1, AILERON_STEPS)[1:]]
        back = [(x, _y_at(lower, x)) for x in _linspace(x2, x_te, AILERON_STEPS)]
        local = local + fwd + [apex] + back
    if twist_deg:
        px, py = 0.25 * chord, 0.0                     # rotate about quarter chord
        c, s = math.cos(math.radians(twist_deg)), math.sin(math.radians(twist_deg))
        # nose-down for positive twist: LE (dx < 0 here, since x runs LE->TE... ) handled below
        rot = []
        for x, y in local:
            dx, dy = x - px, y - py
            # LE is at dx = -px (negative); nose down => LE dy decreases => rotate by +twist
            rot.append((px + dx * c - dy * s, py + dx * s + dy * c))
        local = rot
    # machine X grows toward the LE (front): TE at te_x, LE at te_x + chord
    return [(te_x + chord - x, chord_y + y) for x, y in local]


def _linspace(a: float, b: float, n: int) -> list[float]:
    return [a + (b - a) * i / (n - 1) for i in range(n)]


@dataclass
class WingPath:
    root: list[Point]
    tip: list[Point]
    tower1: list[Point]
    tower2: list[Point]
    entry_root: Point
    entry_tip: Point
    entry_t1: Point
    entry_t2: Point
    s_root: float
    s_tip: float
    tower_gap: float
    block: tuple[float, float, float, float]        # x, y, len, h
    block_s: tuple[float, float] = (0.0, 0.0)       # span range of the block (s values)
    min_block: tuple = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)   # x, y, len, h, start (from root), width
    chord_y: float = 0.0                            # derived chord height
    table_y: float = 0.0                            # table top = block bottom
    table_range: tuple = (0.0, 0.0)                 # lowest / highest table the travel allows
    table_max: tuple = (0.0, 0.0, 0.0, 0.0)         # s_lo, s_hi, x_lo, x_hi the table may occupy
    root_tower: int = 2                             # tower the root plane is nearer to
    mirrored: bool = False
    faces: list = field(default_factory=list)       # [(s, profile points)] at both block faces
    notes: list[str] = field(default_factory=list)

    def section(self, s: float) -> list[Point]:
        """The profile the wire cuts in the plane at span position s."""
        f = (s - self.s_root) / (self.s_tip - self.s_root)
        return [(r[0] + (t[0] - r[0]) * f, r[1] + (t[1] - r[1]) * f)
                for r, t in zip(self.root, self.tip)]

    def extents(self) -> dict[str, tuple[float, float]]:
        pts1 = self.tower1 + [self.entry_t1, (0.0, 0.0)]
        pts2 = self.tower2 + [self.entry_t2, (0.0, 0.0)]
        return {
            "X": (min(p[0] for p in pts1), max(p[0] for p in pts1)),
            "Y": (min(p[1] for p in pts1), max(p[1] for p in pts1)),
            "U": (min(p[0] for p in pts2), max(p[0] for p in pts2)),
            "V": (min(p[1] for p in pts2), max(p[1] for p in pts2)),
        }


def loft(spec, root: list[Point], tip: list[Point], machine: Machine, mirrored: bool = False) -> WingPath:
    """Place two contours (machine X, y relative to their reference line) between
    the towers and wrap them: table, chord height, block, entry, carriage paths.

    `spec` supplies the placement: block_x, lead, table_y (or legacy chord_y),
    margin, root_gap, panel and the block_* overrides. Wings and free shapes
    share this; what differs is how the contours are made.
    """
    gap = machine.tower_gap_mm
    root_tower = machine.wire_fixed_tower
    if spec.root_gap + spec.panel > gap:
        raise WingError(f"root_gap + panel = {spec.root_gap + spec.panel:g} mm, "
                        f"aber der Turmabstand ist nur {gap:g} mm")
    if root_tower == 1:
        s_root, s_tip = spec.root_gap, spec.root_gap + spec.panel
    else:
        s_root, s_tip = gap - spec.root_gap, gap - spec.root_gap - spec.panel

    def extrapolate(pr: Point, pt: Point, s: float) -> Point:
        f = (s - s_root) / (s_tip - s_root)
        return (pr[0] + (pt[0] - pr[0]) * f, pr[1] + (pt[1] - pr[1]) * f)

    # where the foam is along the span, and what the wire cuts at its two faces
    toward_tip = 1.0 if s_tip > s_root else -1.0
    start = spec.block_s or 0.0
    width = spec.block_w if spec.block_w is not None else max(spec.panel + spec.margin - start, 0.0)
    s_a = s_root + toward_tip * start
    s_b = s_a + toward_tip * width
    faces_rel = [[extrapolate(pr, pt, sv) for pr, pt in zip(root, tip)] for sv in (s_a, s_b)]
    min_rel = min(q[1] for f in faces_rel for q in f)      # lowest cut point relative to the chord
    m = spec.margin
    if spec.chord_y is not None:                           # legacy file: chord given, table follows
        chord_y, table_y = spec.chord_y, spec.chord_y + min_rel - m
    else:
        table_y = spec.table_y
        chord_y = table_y + m - min_rel                    # profile sits `margin` above the table
    lift = lambda pts: [(x, y + chord_y) for x, y in pts]
    root, tip = lift(root), lift(tip)
    tower1 = [extrapolate(pr, pt, 0.0) for pr, pt in zip(root, tip)]
    tower2 = [extrapolate(pr, pt, gap) for pr, pt in zip(root, tip)]

    entry_root = entry_tip = (spec.block_x, chord_y)
    entry_t1 = extrapolate(entry_root, entry_tip, 0.0)
    entry_t2 = extrapolate(entry_root, entry_tip, gap)

    path = WingPath(root, tip, tower1, tower2, entry_root, entry_tip, entry_t1, entry_t2,
                    s_root, s_tip, gap, (0.0, 0.0, 0.0, 0.0), root_tower=root_tower, mirrored=mirrored,
                    chord_y=chord_y, table_y=table_y)
    path.block_s = (s_a, s_b)
    path.faces = [(s_a, lift(faces_rel[0])), (s_b, lift(faces_rel[1]))]

    # smallest block that holds the cut with the margins: back face at block_x
    # (the wire enters there), bottom on the table, everything else profile plus margin
    fpts = path.faces[0][1] + path.faces[1][1]
    xmax = max(q[0] for q in fpts) + m
    ymin, ymax = min(q[1] for q in fpts) - m, max(q[1] for q in fpts) + m
    path.min_block = (spec.block_x, ymin, xmax - spec.block_x, ymax - ymin, start, width)
    bx = spec.block_x
    bl = spec.block_len if spec.block_len is not None else xmax - bx
    by = table_y                                            # the block lies on the table
    bh = spec.block_h if spec.block_h is not None else ymax - ymin
    path.block = (bx, by, bl, bh)

    # table: how low/high the travel allows it, and how far it may reach before
    # the wire (extrapolated beyond the block) would dip into it
    carriage = tower1 + tower2 + [entry_t1, entry_t2]
    off_min = min(q[1] for q in carriage) - chord_y
    off_max = max(q[1] for q in carriage) - chord_y
    t_lo = min_rel - m - off_min                            # carriages just reach Y=0
    t_hi = (min(machine.travel_mm["Y"], machine.travel_mm["V"]) - (m - min_rel + off_max)
            if machine.has_travel() else float("inf"))
    path.table_range = (t_lo, t_hi)
    limit = table_y + TABLE_CLEARANCE

    def clear(sv: float) -> bool:
        return min(q[1] for q in path.section(sv)) >= limit

    s_lo, s_hi = min(s_a, s_b), max(s_a, s_b)
    while s_lo - 1.0 >= 0.0 and clear(s_lo - 1.0):
        s_lo -= 1.0
    while s_hi + 1.0 <= gap and clear(s_hi + 1.0):
        s_hi += 1.0
    path.table_max = (max(s_lo, 0.0), min(s_hi, gap), TABLE_REST_CLEARANCE, xmax)

    path.notes.append(f"Wurzel an Turm {root_tower} (Draht fest, s={s_root:g}), Ende bei s={s_tip:g}, "
                      f"Turmabstand {gap:g}" + (", SPIEGELVERKEHRT (Profil kopfueber)" if mirrored else ""))
    path.notes.append(f"Mindestblock: {xmax - bx:.0f} x {ymax - ymin:.0f} x "
                      f"{width:.0f} mm (Laenge x Hoehe x Breite), Rueckseite X={bx:g}, "
                      f"Unterkante Y={ymin:.1f}, ab Wurzelebene {start:g}")
    hi_txt = f"{t_hi:.1f}" if t_hi != float("inf") else "?"
    path.notes.append(f"Tisch: Oberkante Y={table_y:.1f} (moeglich {t_lo:.1f} bis {hi_txt}), Sehne Y={chord_y:.1f}; "
                      f"maximal s={path.table_max[0]:.0f}..{path.table_max[1]:.0f} "
                      f"(Breite {path.table_max[1] - path.table_max[0]:.0f} mm), X ab {TABLE_REST_CLEARANCE:g} nach vorn")
    if table_y < t_lo - 1e-6:
        path.notes.append(f"Tisch zu niedrig: Schlitten muessten unter Y=0 ({t_lo:.1f} ist das Minimum)")
    if table_y > t_hi + 1e-6:
        path.notes.append(f"Tisch zu hoch: Schlitten ueber dem Verfahrweg ({t_hi:.1f} ist das Maximum)")
    if not machine.tower_gap_measured:
        path.notes.append("TURMABSTAND NICHT GEMESSEN - 800 ist ein Platzhalter. Abstand der "
                          "Drahtaufhaengungen messen und eintragen; er skaliert den Schnitt.")
    if start > 0 or spec.block_w is not None:
        desc = []
        for s, pts in path.faces:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            desc.append(f"{max(xs) - min(xs):.1f} x {max(ys) - min(ys):.1f}")
        path.notes.append(f"Block bei s={min(s_a, s_b):g}..{max(s_a, s_b):g}: Profil dort "
                          f"{desc[0]} mm / {desc[1]} mm (Tiefe x Dicke)")
    if min(s_a, s_b) < 0 or max(s_a, s_b) > gap:
        path.notes.append("Block liegt ausserhalb der Tuerme!")
    for label, pts in (("wurzelseitige Blockflaeche", path.faces[0][1]),
                       ("endseitige Blockflaeche", path.faces[1][1])):
        ys = [p[1] for p in pts]
        xs = [p[0] for p in pts]
        if min(ys) < by or max(ys) > by + bh or min(xs) < bx or max(xs) > bx + bl:
            path.notes.append(f"Profil ragt aus dem Block ({label})")
    return path


def build_path(spec: WingSpec, machine: Machine, airfoil_dir: Path) -> WingPath:
    root_file = _resolve(spec.root_airfoil, airfoil_dir)
    tip_file = _resolve(spec.tip_airfoil, airfoil_dir)
    _, r_up, r_lo = af.load(root_file)
    _, t_up, t_lo = af.load(tip_file)
    loop_r = af.resample_loop(r_up, r_lo, spec.points)
    loop_t = af.resample_loop(t_up, t_lo, spec.points)

    # the rearmost trailing edge sits `lead` in front of the block face; the
    # wire enters at the face and cuts straight in along the chord line
    rear = min(0.0, spec.root_chord - spec.sweep - spec.tip_chord)     # < 0: the tip TE is further back
    te_x = spec.block_x + spec.lead - rear
    tip_te_x = te_x + spec.root_chord - spec.sweep - spec.tip_chord
    # build relative to the chord line (y = 0) first: the chord height follows
    # from the table below, which needs the profile's lowest point
    ail = (spec.aileron, spec.hinge_skin, spec.hinge_v) if spec.aileron > 0 else None
    root = _profile_mm(loop_r, spec.root_chord, te_x, 0.0, 0.0, machine.kerf_mm, ail)
    tip = _profile_mm(loop_t, spec.tip_chord, tip_te_x, 0.0, spec.washout, machine.kerf_mm, ail)
    if spec.mirror:
        # upside down about the chord line; turning the cut piece over about its
        # chord axis then gives the mirror-image (opposite-hand) panel
        root = [(x, -y) for x, y in root]
        tip = [(x, -y) for x, y in tip]

    path = loft(spec, root, tip, machine, mirrored=spec.mirror)
    if ail:
        path.notes.append(f"Ruderschnitt: Scharnier bei {spec.aileron:g} % der Tiefe ab Hinterkante, "
                          f"Haut {spec.hinge_skin:g} mm, Kerbe {spec.hinge_v:g} mm - ueber die ganze Blockbreite")
    gap, s_root, s_tip = path.tower_gap, path.s_root, path.s_tip
    if spec.dihedral:
        # the root face would have to tilt `dihedral` from vertical about the
        # chord axis; the wire cannot do that, so say what to sand or build
        ys = [q[1] for q in root]
        t = max(ys) - min(ys)
        wedge = t * math.tan(math.radians(abs(spec.dihedral)))
        rise = spec.panel * math.sin(math.radians(abs(spec.dihedral)))
        path.notes.append(f"V-Form {spec.dihedral:g} deg: Wurzelflaeche um {wedge:.1f} mm keilfoermig schleifen "
                          f"(Dicke {t:.1f} mm) oder Winkel im Verbinder; das Ende steht dann {rise:.0f} mm hoeher "
                          "als die Wurzel. Der Schnitt selbst bleibt gerade.")

    c_r, c_t = spec.root_chord, spec.tip_chord
    if abs(c_r - c_t) > 1e-9:
        f_apex = c_r / (c_r - c_t)
        s_apex = s_root + (s_tip - s_root) * f_apex
        if 0 <= s_apex <= gap:
            path.notes.append(f"Drahtlinien kreuzen sich bei s={s_apex:.0f} (Profiltiefe 0, dahinter "
                              "gespiegelt) - dort darf kein Schaum liegen")

    return path


def _resolve(name: str, airfoil_dir: Path) -> Path:
    p = Path(name)
    for cand in (p, airfoil_dir / name, airfoil_dir / f"{name}.dat"):
        if cand.exists():
            return cand
    raise WingError(f"Profil nicht gefunden: {name} (gesucht in {airfoil_dir})")


# -------------------------------------------------------------- g-code ------
def wing_name(spec: WingSpec) -> str:
    """File name for a generated program, e.g. clarky_100-80_400.nc / ..._sp.nc."""
    return (f"{spec.root_airfoil.rsplit('.', 1)[0]}_{spec.root_chord:g}-{spec.tip_chord:g}_{spec.panel:g}"
            + ("_sp" if spec.mirror else "") + ".nc")


@dataclass
class Model:
    """What the design page needs to drive one kind of cut (wing, shape)."""
    title: str
    key: str                    # UiState key and file suffix (.wing / .shape)
    fields: list
    parse: object               # text -> spec
    generate: object            # (spec, machine, airfoil_dir) -> (code, path)
    name: object                # spec -> file name
    to_text: object             # values -> text
    from_text: object           # text -> values
    template: str
    file_filter: str

    def values_from_file(self, text: str, machine: Machine, airfoil_dir: Path) -> dict[str, str]:
        return self.from_text(text)


def inverted(contour: list[Point], tower: list[Point]) -> bool:
    """True when the wire lines have crossed before this tower: the contour
    there is the point-reflected one (rear and front swapped). A signed area
    cannot tell - a point reflection keeps the orientation - so compare the
    rear->front vector of the block face with the tower's."""
    n = len(contour)
    if n < 3:
        return False
    k = max(range(n), key=lambda i: math.dist(contour[i], contour[0]))
    ax, ay = contour[k][0] - contour[0][0], contour[k][1] - contour[0][1]
    bx, by = tower[k][0] - tower[0][0], tower[k][1] - tower[0][1]
    return ax * bx + ay * by < 0


def _w(p1: Point, p2: Point) -> str:
    return f"X{p1[0]:.3f} Y{p1[1]:.3f} U{p2[0]:.3f} V{p2[1]:.3f}"


def emit_gcode(path: WingPath, feed: float, wire: int, warmup: float, header: list[str]) -> str:
    """The one-pass program for a lofted path: heat, lift, approach, contour
    with inverse-time feed, exit, retreat over the table, lower."""
    s_wire = wire if wire > 0 else 1          # S1 = "use the GUI slider" (translate())
    out = list(header) + [
        "; " + path.notes[0],
        "G21 ; mm",
        "G90 ; absolut",
        "G94",
        f"M3 S{s_wire}" + (" ; Drahtleistung vom GUI-Schieber" if wire <= 0 else ""),
        f"G4 P{warmup:g} ; aufheizen",
        f"G0 Y{path.entry_t1[1]:.3f} V{path.entry_t2[1]:.3f} ; erst heben (Tisch!)",
        f"G0 X{path.entry_t1[0]:.3f} U{path.entry_t2[0]:.3f} ; dann vor zur Blockrueckseite",
        "G93 ; inverse Zeit: F = 1/min je Segment",
    ]
    total_min = 0.0
    prev_r, prev_t = path.entry_root, path.entry_tip
    contact = [(path.root[0], path.tip[0])] + list(zip(path.root, path.tip))[1:] \
        + [(path.entry_root, path.entry_tip)]
    towers = [(path.tower1[0], path.tower2[0])] + list(zip(path.tower1, path.tower2))[1:] \
        + [(path.entry_t1, path.entry_t2)]
    for (pr, pt), (p1, p2) in zip(contact, towers):
        seg = max(math.dist(prev_r, pr), math.dist(prev_t, pt))
        if seg < 1e-6:
            prev_r, prev_t = pr, pt
            continue
        minutes = seg / feed
        total_min += minutes
        out.append(f"G1 {_w(p1, p2)} F{1.0 / minutes:.4f}")
        prev_r, prev_t = pr, pt
    out += [
        "G94",
        # Retreat at cut feed with the wire hot: if the block sits further back than
        # the spec says, the wire is still in foam here - a rapid would tear, a cold
        # wire would stick.
        f"G1 X0 U0 F{feed:g} ; zurueck ueber dem Tisch, Draht noch heiss, Schnittvorschub",
        "M5 ; Draht aus, erst bei X0/U0",
        "G0 Y0 V0 ; dann senken",
        "M2",
    ]
    path.notes.append(f"Schnittzeit ca. {total_min:.1f} min, {len(path.root)} Stuetzpunkte")
    return "\n".join(out) + "\n"


def generate(spec: WingSpec, machine: Machine, airfoil_dir: Path) -> tuple[str, WingPath]:
    path = build_path(spec, machine, airfoil_dir)
    header = [
        f"; foamcut wing: {spec.root_airfoil} {spec.root_chord:g} -> "
        f"{spec.tip_airfoil} {spec.tip_chord:g}, Panel {spec.panel:g}"
        + (", spiegelverkehrt" if spec.mirror else "") + (f", Ruder {spec.aileron:g} %" if spec.aileron > 0 else ""),
        f"; Pfeilung {spec.sweep:g}, Schraenkung {spec.washout:g} deg, Kerf {machine.kerf_mm:g}, "
        f"Vorschub {machine.cut_feed:g} mm/min",
    ]
    return emit_gcode(path, machine.cut_feed, machine.wire_power, machine.warmup_s, header), path


def _wing_values_from_file(self, text: str, machine: Machine, airfoil_dir: Path) -> dict[str, str]:
    """Form values from a .wing file; an old file with chord_y gets its table_y derived."""
    vals = from_text(text)
    try:
        spec = WingSpec.parse(text)
        if spec.chord_y is not None:
            vals["table_y"] = f"{build_path(spec, machine, airfoil_dir).table_y:.1f}"
    except (WingError, ValueError, OSError):
        pass
    return vals


WING_MODEL = Model("Flügel", "wing", FIELDS, WingSpec.parse, generate, wing_name, to_text, from_text,
                   TEMPLATE, "wing (*.wing);;alle (*)")
WING_MODEL.values_from_file = _wing_values_from_file.__get__(WING_MODEL)
