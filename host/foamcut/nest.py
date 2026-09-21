"""Nesting: several parts (wings, shapes) in one block, one program.

Every part keeps its own file; the batch says which parts, in which order
(top first), how far apart, and where the block sits. Parts are stacked in Y:
the next part's lowest wire line lies `gap` above the highest wire line of
the part below - checked along the *whole* block width, because a shorter
part's wire keeps cutting its extrapolated profile past its own tip until
the far block face. Between parts the wire retreats 5 mm behind the block
face (no foam there) and travels vertically, so it never crosses a cut part.

A pair (`pair = ja`) adds the mirror-image panel of a wing: the same contours
with root and tip swapped along the span, so its thin end lies over the thick
root of the original. Its root then sits at the weight tower.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import AXES
from .machine import Machine
from .shape import SHAPE_MODEL
from .wing import (TABLE_CLEARANCE, TABLE_REST_CLEARANCE, WING_MODEL, Point, WingError, WingPath, _w)

APPROACH = 5.0          # mm behind the block face where the wire travels between parts
SPAN_STEP = 5.0         # mm, sampling along the span for the stacking check


@dataclass
class Item:
    file: str
    pair: bool = False          # also cut the mirror-image (span-reversed) panel above it
    dy: float = 0.0             # result: how far this part was lifted above the table


@dataclass
class Batch:
    block_x: float = 20.0
    table_y: float = 20.0
    root_gap: float = 150.0
    gap: float = 8.0            # foam left between stacked parts
    block_len: float | None = None      # given block, X; None = just report the minimum
    block_h: float | None = None        # given block, Y
    block_w: float | None = None        # given block, span
    items: list[Item] = field(default_factory=list)

    # ------------------------------------------------------------ text -----
    def to_text(self) -> str:
        out = ["; foamcut batch - mehrere Teile in einem Block, von oben nach unten geschnitten", "",
               "[block]", f"block_x = {self.block_x:g}", f"table_y = {self.table_y:g}", f"root_gap = {self.root_gap:g}",
               f"gap = {self.gap:g}",
               f"block_len = {'' if self.block_len is None else f'{self.block_len:g}'}",
               f"block_h = {'' if self.block_h is None else f'{self.block_h:g}'}",
               f"block_w = {'' if self.block_w is None else f'{self.block_w:g}'}", "", "[teile]"]
        for it in self.items:
            out.append(f"teil = {it.file}" + (" ; paar" if it.pair else ""))
        return "\n".join(out) + "\n"

    @classmethod
    def parse(cls, text: str, base: Path | None = None) -> "Batch":
        b = cls(items=[])
        nums = {"block_x", "table_y", "root_gap", "gap", "block_len", "block_h", "block_w"}
        for n, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            body = line.split(";", 1)[0].strip()
            if not body or body.startswith("["):
                continue
            key, _, value = body.partition("=")
            key, value = key.strip().lower(), value.strip()
            if key == "teil":
                pair = "paar" in line.split(";", 1)[1].lower() if ";" in line else False
                b.items.append(Item(str((base / value) if base and not Path(value).is_absolute() else value), pair))
            elif key in nums:
                if value == "":
                    continue
                try:
                    setattr(b, key, float(value.replace(",", ".")))
                except ValueError:
                    raise WingError(f"Zeile {n}: {key} braucht eine Zahl") from None
            else:
                raise WingError(f"Zeile {n}: unbekannter Parameter {key!r}")
        return b


@dataclass
class Placed:
    """One lofted part inside the batch, in machine coordinates."""
    name: str
    path: WingPath
    approach: tuple[Point, Point]       # tower 1 / tower 2 points 5 mm behind the face
    top: float                          # highest wire line over the block width
    bottom: float


@dataclass
class Nest:
    parts: list[Placed]
    block: tuple[float, float, float, float]        # x, y, len, h (minimum or given)
    min_block: tuple[float, float, float, float, float]   # x, y, len, h, width
    block_s: tuple[float, float]
    table_y: float
    table_range: tuple[float, float]
    table_max: tuple[float, float, float, float]
    notes: list[str] = field(default_factory=list)

    # what the drawing code expects from a WingPath, taken from the first part
    @property
    def path(self) -> WingPath:
        return self.parts[0].path

    def extents(self) -> dict[str, tuple[float, float]]:
        pts1 = [(0.0, 0.0)]; pts2 = [(0.0, 0.0)]
        for pl in self.parts:
            pts1 += pl.path.tower1 + [pl.path.entry_t1, pl.approach[0]]
            pts2 += pl.path.tower2 + [pl.path.entry_t2, pl.approach[1]]
        return {"X": (min(p[0] for p in pts1), max(p[0] for p in pts1)),
                "Y": (min(p[1] for p in pts1), max(p[1] for p in pts1)),
                "U": (min(p[0] for p in pts2), max(p[0] for p in pts2)),
                "V": (min(p[1] for p in pts2), max(p[1] for p in pts2))}


def _load_spec(file: str, machine: Machine, airfoil_dir: Path):
    p = Path(file)
    text = p.read_text()
    model = SHAPE_MODEL if p.suffix == ".shape" else WING_MODEL
    return model, model.parse(text)


def _relative_part(model, spec, batch: Batch, machine: Machine, airfoil_dir: Path, reversed_span: bool):
    """Loft one part with table at 0 and the batch's block placement; returns
    (root, tip, entry) with y relative to that part's own table."""
    spec = copy.deepcopy(spec)
    spec.block_x, spec.root_gap, spec.table_y = batch.block_x, batch.root_gap, 0.0
    spec.chord_y = None
    spec.block_s = spec.block_w = spec.block_len = spec.block_h = None
    _, path = model.generate(spec, machine, airfoil_dir)
    root, tip = path.root, path.tip
    if reversed_span:
        root, tip = tip, root
    return root, tip, path.entry_root, spec


def build(batch: Batch, machine: Machine, airfoil_dir: Path) -> Nest:
    if not batch.items:
        raise WingError("keine Teile in der Liste")
    gap_t = machine.tower_gap_mm
    if machine.wire_fixed_tower == 1:
        s_root = batch.root_gap; toward = 1.0
    else:
        s_root = gap_t - batch.root_gap; toward = -1.0

    # 1. every part relative to its own table, longest panel sets the block width
    raw = []
    for it in batch.items:
        model, spec = _load_spec(it.file, machine, airfoil_dir)
        root, tip, entry, spec = _relative_part(model, spec, batch, machine, airfoil_dir, False)
        raw.append((Path(it.file).name, spec, root, tip, entry))
        if it.pair:
            r2, t2, e2, _ = _relative_part(model, spec, batch, machine, airfoil_dir, True)
            raw.append((Path(it.file).name + " (Paar)", spec, r2, t2, e2))
    max_panel = max(sp.panel for _, sp, *_ in raw)
    margin = max(sp.margin for _, sp, *_ in raw)
    width = batch.block_w if batch.block_w is not None else max_panel + margin
    if batch.root_gap + width > gap_t:
        raise WingError(f"root_gap + Blockbreite = {batch.root_gap + width:g} mm, Turmabstand nur {gap_t:g}")
    s_far = s_root + toward * width
    samples = [s_root + toward * k * SPAN_STEP for k in range(int(width / SPAN_STEP) + 1)] + [s_far]

    def section(root, tip, s_tip, s):
        f = (s - s_root) / (s_tip - s_root)
        return [(r[0] + (t[0] - r[0]) * f, r[1] + (t[1] - r[1]) * f) for r, t in zip(root, tip)]

    # 2. stack from the top of the list downwards: last item lies on the table,
    #    every earlier one above it. Cut order = list order (top first).
    profiles = []
    for name, spec, root, tip, entry in raw:
        s_tip = s_root + toward * spec.panel
        secs = [section(root, tip, s_tip, s) for s in samples]
        top = [max(q[1] for q in sec) for sec in secs]
        bot = [min(q[1] for q in sec) for sec in secs]
        profiles.append((name, spec, root, tip, entry, s_tip, top, bot))
    dys = [0.0] * len(profiles)
    floor_top = None                        # top(s) of the part below, absolute
    for i in range(len(profiles) - 1, -1, -1):
        name, spec, root, tip, entry, s_tip, top, bot = profiles[i]
        if floor_top is None:
            dy = batch.table_y + margin - min(bot)          # lowest wire line `margin` above the table
        else:
            dy = max(ft - b for ft, b in zip(floor_top, bot)) + batch.gap
        dys[i] = dy
        floor_top = [t + dy for t in top]

    # 3. absolute paths, entries, approach points
    placed: list[Placed] = []
    for (name, spec, root, tip, entry, s_tip, top, bot), dy in zip(profiles, dys):
        lift = lambda pts: [(x, y + dy) for x, y in pts]
        root_a, tip_a = lift(root), lift(tip)
        cy = entry[1] + dy

        def ext(pr, pt, s):
            f = (s - s_root) / (s_tip - s_root)
            return (pr[0] + (pt[0] - pr[0]) * f, pr[1] + (pt[1] - pr[1]) * f)

        tower1 = [ext(pr, pt, 0.0) for pr, pt in zip(root_a, tip_a)]
        tower2 = [ext(pr, pt, gap_t) for pr, pt in zip(root_a, tip_a)]
        e = (batch.block_x, cy)
        path = WingPath(root_a, tip_a, tower1, tower2, e, e, e, e, s_root, s_tip, gap_t,
                        (0.0, 0.0, 0.0, 0.0), root_tower=machine.wire_fixed_tower, chord_y=cy, table_y=batch.table_y)
        path.block_s = (s_root, s_far)
        path.faces = [(s_root, root_a), (s_far, section(root_a, tip_a, s_tip, s_far))]
        app = (batch.block_x - APPROACH, cy)
        placed.append(Placed(name, path, (app, app), max(top) + dy, min(bot) + dy))

    # 4. block, table
    all_secs = [q for pl in placed for sec in pl.path.faces for q in sec[1]]
    x_hi = max(q[0] for q in all_secs) + margin
    y_hi = max(pl.top for pl in placed) + margin
    min_block = (batch.block_x, batch.table_y, x_hi - batch.block_x, y_hi - batch.table_y, width)
    bl = batch.block_len if batch.block_len is not None else min_block[2]
    bh = batch.block_h if batch.block_h is not None else min_block[3]
    block = (batch.block_x, batch.table_y, bl, bh)
    carriage = [q for pl in placed for q in pl.path.tower1 + pl.path.tower2]
    y_min, y_max = min(q[1] for q in carriage), max(q[1] for q in carriage)
    t_lo = batch.table_y - y_min
    t_hi = (batch.table_y + min(machine.travel_mm["Y"], machine.travel_mm["V"]) - y_max
            if machine.has_travel() else float("inf"))
    limit = batch.table_y + TABLE_CLEARANCE

    def clear(s):
        return all(min(q[1] for q in pl.path.section(s)) >= limit for pl in placed)

    lo, hi = min(s_root, s_far), max(s_root, s_far)
    while lo - 1.0 >= 0.0 and clear(lo - 1.0):
        lo -= 1.0
    while hi + 1.0 <= gap_t and clear(hi + 1.0):
        hi += 1.0
    nest = Nest(placed, block, min_block, (s_root, s_far), batch.table_y, (t_lo, t_hi),
                (max(lo, 0.0), min(hi, gap_t), TABLE_REST_CLEARANCE, x_hi))
    order = ", ".join(f"{pl.name} (Y {pl.bottom:.1f}..{pl.top:.1f})" for pl in placed)
    nest.notes.append(f"{len(placed)} Teile, Wurzel an Turm {machine.wire_fixed_tower} (s={s_root:g}), "
                      f"Reihenfolge von oben: {order}")
    nest.notes.append(f"Mindestblock: {min_block[2]:.0f} x {min_block[3]:.0f} x {width:.0f} mm (Laenge x Hoehe x Breite), "
                      f"Rueckseite X={batch.block_x:g}, Unterkante Y={batch.table_y:g}")
    if batch.block_len is not None and bl < min_block[2] - 1e-6:
        nest.notes.append(f"Block zu kurz: {bl:g} mm gegeben, {min_block[2]:.0f} noetig")
    if batch.block_h is not None and bh < min_block[3] - 1e-6:
        nest.notes.append(f"Block zu niedrig: {bh:g} mm gegeben, {min_block[3]:.0f} noetig")
    if batch.block_w is not None and batch.block_w < max_panel - 1e-6:
        nest.notes.append(f"Block zu schmal: {batch.block_w:g} mm gegeben, laengstes Teil {max_panel:g}")
    hi_txt = f"{t_hi:.1f}" if t_hi != float("inf") else "?"
    nest.notes.append(f"Tisch: Oberkante Y={batch.table_y:g} (moeglich {t_lo:.1f} bis {hi_txt}); maximal "
                      f"s={nest.table_max[0]:.0f}..{nest.table_max[1]:.0f}, X ab {TABLE_REST_CLEARANCE:g}")
    if batch.table_y < t_lo - 1e-6:
        nest.notes.append(f"Tisch zu niedrig: Schlitten muessten unter Y=0 ({t_lo:.1f} ist das Minimum)")
    if batch.table_y > t_hi + 1e-6:
        nest.notes.append(f"Tisch zu hoch: Schlitten ueber dem Verfahrweg ({t_hi:.1f} ist das Maximum)")
    return nest


def emit(nest: Nest, feed: float, wire: int, warmup: float) -> str:
    """One program: heat, then for every part approach behind the face,
    enter, contour, back out to the approach point; retreat, lower."""
    s_wire = wire if wire > 0 else 1
    out = [f"; foamcut nest: {len(nest.parts)} Teile in einem Block", "; " + nest.notes[0],
           "G21", "G90", "G94", f"M3 S{s_wire}" + (" ; Drahtleistung vom GUI-Schieber" if wire <= 0 else ""),
           f"G4 P{warmup:g} ; aufheizen"]
    total_min = 0.0
    first = True
    for pl in nest.parts:
        p = pl.path
        a1, a2 = pl.approach
        out.append(f"; --- {pl.name}")
        if first:
            out.append(f"G0 Y{a1[1]:.3f} V{a2[1]:.3f} ; erst heben (Tisch!)")
            out.append(f"G0 X{a1[0]:.3f} U{a2[0]:.3f} ; vor bis kurz hinter die Blockrueckseite")
            first = False
        else:
            out.append(f"G0 {_w(a1, a2)} ; hinter der Blockrueckseite zum naechsten Teil")
        out.append("G93")
        prev = (a1, a2)
        contact = [(p.entry_root, p.entry_tip)] + [(p.root[0], p.tip[0])] + list(zip(p.root, p.tip))[1:] \
            + [(p.entry_root, p.entry_tip), (a1, a2)]
        towers = [(p.entry_t1, p.entry_t2)] + [(p.tower1[0], p.tower2[0])] + list(zip(p.tower1, p.tower2))[1:] \
            + [(p.entry_t1, p.entry_t2), (a1, a2)]
        for (pr, pt), (t1, t2) in zip(contact, towers):
            seg = max(math.dist(prev[0], pr), math.dist(prev[1], pt))
            if seg < 1e-6:
                prev = (pr, pt); continue
            minutes = seg / feed
            total_min += minutes
            out.append(f"G1 {_w(t1, t2)} F{1.0 / minutes:.4f}")
            prev = (pr, pt)
        out.append("G94")
    out += ["M5 ; Draht aus", "G0 X0 U0 ; zurueck, ueber dem Tisch", "G0 Y0 V0 ; dann senken", "M2"]
    nest.notes.append(f"Schnittzeit ca. {total_min:.1f} min")
    return "\n".join(out) + "\n"


def generate(batch: Batch, machine: Machine, airfoil_dir: Path) -> tuple[str, Nest]:
    nest = build(batch, machine, airfoil_dir)
    return emit(nest, machine.cut_feed, machine.wire_power, machine.warmup_s), nest
