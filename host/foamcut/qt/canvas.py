"""Millimetre canvases: a QWidget that maps mm to pixels and draws with QPainter.

FrontView / TopView draw a WingPath, SimView one tower of a simulation.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from .. import AXES
from .uiload import load_ui

# (key, checkbox text) - what the wing views can show or hide, in display order
LAYERS = [
    ("root", "Wurzel"), ("tip", "Ende"), ("faces", "Blockflächen"), ("t1", "Turm 1"), ("t2", "Turm 2"),
    ("block", "Block"), ("table", "Tisch"), ("travel", "Verfahrweg"), ("entry", "Ein-/Auslauf"), ("legend", "Legende"),
]

C = {
    "root": QColor("#1f5fbf"), "tip": QColor("#1a9641"), "t1": QColor("#7aa6e0"), "t2": QColor("#8fd19e"),
    "block": QColor("#c8b27a"), "face": QColor("#8a5a00"), "ref": QColor("#c0392b"), "entry": QColor("#e67e22"),
    "grid": QColor("#ececec"), "axis": QColor("#9a9a9a"), "text": QColor("#444"), "rapid": QColor("#b0b0b0"),
    "travel": QColor("#c8b27a"), "bg": QColor("white"), "table": QColor("#7f7f7f"),
    "live": QColor("#d62728"), "trail": QColor("#ff9896"),
}


class MmCanvas(QWidget):
    """Fits a mm box into the widget; subclasses implement draw(p).

    Title and raster size are not painted here: a ViewFrame shows them in
    labels above the canvas (`raster_changed` tells it the current step).
    """

    raster_changed = pyqtSignal(str)

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.step = 0.0
        self.layers = {key: True for key, _ in LAYERS}
        self.box = (0.0, 1.0, 0.0, 1.0)      # xmin, xmax, ymin, ymax in mm
        self.pad = 26
        self.s = 1.0
        self.ox = self.oy = 0.0
        self.setMinimumHeight(160)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), C["bg"])
        self.setPalette(pal)

    def set_layers(self, shown: dict[str, bool]):
        self.layers.update(shown)
        self.update()

    def on(self, key: str) -> bool:
        return self.layers.get(key, True)

    # ---- transform ------------------------------------------------------
    def set_box(self, xmin, xmax, ymin, ymax, margin: float = 0.05):
        dx = max(xmax - xmin, 1e-6)
        dy = max(ymax - ymin, 1e-6)
        self.box = (xmin - dx * margin, xmax + dx * margin, ymin - dy * margin, ymax + dy * margin)
        step = 10.0 if (self.box[1] - self.box[0]) < 300 else 50.0
        if step != self.step:
            self.step = step
            self.raster_changed.emit(f"{step:g} mm Raster")

    def _fit(self):
        w, h = max(self.width(), 50), max(self.height(), 50)
        xmin, xmax, ymin, ymax = self.box
        self.s = min((w - 2 * self.pad) / (xmax - xmin), (h - 2 * self.pad) / (ymax - ymin))
        self.ox = self.pad + ((w - 2 * self.pad) - (xmax - xmin) * self.s) / 2 - xmin * self.s
        self.oy = h - (self.pad + ((h - 2 * self.pad) - (ymax - ymin) * self.s) / 2) + ymin * self.s

    def tr(self, x: float, y: float) -> QPointF:
        return QPointF(self.ox + x * self.s, self.oy - y * self.s)

    # ---- primitives -----------------------------------------------------
    def polyline(self, p: QPainter, pts, colour, width=2.0, dash=False):
        if len(pts) < 2:
            return
        pen = QPen(colour, width)
        if dash:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        prev = self.tr(*pts[0])
        for q in pts[1:]:
            cur = self.tr(*q)
            p.drawLine(prev, cur)
            prev = cur

    def rect_mm(self, p: QPainter, x0, y0, x1, y1, colour, width=2.0, dash=False):
        pen = QPen(colour, width)
        if dash:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        a, b = self.tr(x0, y0), self.tr(x1, y1)
        p.drawRect(QRectF(a, b).normalized())

    def label(self, p: QPainter, x, y, text, colour, dx=4, dy=-4, size=8):
        p.setPen(QPen(colour))
        p.setFont(QFont("Sans", size))
        q = self.tr(x, y)
        p.drawText(QPointF(q.x() + dx, q.y() + dy), text)

    def grid(self, p: QPainter, with_axes=True):
        xmin, xmax, ymin, ymax = self.box
        step = self.step or 10.0
        p.setPen(QPen(C["grid"], 1))
        x = math.floor(xmin / step) * step
        while x <= xmax:
            a = self.tr(x, ymin); b = self.tr(x, ymax)
            p.drawLine(a, b); x += step
        y = math.floor(ymin / step) * step
        while y <= ymax:
            a = self.tr(xmin, y); b = self.tr(xmax, y)
            p.drawLine(a, b); y += step
        if with_axes:
            p.setPen(QPen(C["axis"], 1))
            p.drawLine(self.tr(xmin, 0), self.tr(xmax, 0))
            p.drawLine(self.tr(0, ymin), self.tr(0, ymax))

    def paintEvent(self, ev):
        self._fit()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.draw(p)
        p.end()

    def draw(self, p: QPainter):  # pragma: no cover - overridden
        pass


class ViewFrame(QWidget):
    """Header row (title, raster size) above a canvas - see ui/viewframe.ui."""

    def __init__(self, canvas: MmCanvas, parent=None):
        super().__init__(parent)
        load_ui("viewframe", self)
        self.canvas = canvas
        self.title.setText(canvas.title)
        self.canvas_layout.addWidget(canvas)
        canvas.raster_changed.connect(self.raster.setText)


class FrontView(MmCanvas):
    """X/Y plane: root, tip, block faces, carriage paths, block, travel."""

    def __init__(self, parent=None):
        super().__init__("Vorderansicht   X vorne →   Y oben ↑", parent)
        self.path = None
        self.machine = None
        self.extra = []

    def show_path(self, path, machine, extra=()):
        """`extra`: further WingPaths (nesting) drawn in the same colours, thinner."""
        self.path, self.machine, self.extra = path, machine, list(extra)
        if path:
            bx, by, bl, bh = path.block
            pts = path.root + path.tip + path.tower1 + path.tower2 + [(0, 0), (bx, by), (bx + bl, by + bh)]
            for q in self.extra:
                pts += q.root + q.tip + q.tower1 + q.tower2
            if machine.has_travel():
                pts += [(machine.travel_mm["X"], machine.travel_mm["Y"]), (machine.travel_mm["U"], machine.travel_mm["V"])]
            self.set_box(min(q[0] for q in pts), max(q[0] for q in pts), min(q[1] for q in pts), max(q[1] for q in pts))
        self.update()

    def draw(self, p):
        self.grid(p)
        if not self.path:
            return
        path, m = self.path, self.machine
        on = self.on
        if on("travel") and m.has_travel():
            self.rect_mm(p, 0, 0, m.travel_mm["X"], m.travel_mm["Y"], C["t1"], 1, dash=True)
            self.rect_mm(p, 0, 0, m.travel_mm["U"], m.travel_mm["V"], C["t2"], 1, dash=True)
        if on("block"):
            bx, by, bl, bh = path.block
            self.rect_mm(p, bx, by, bx + bl, by + bh, C["block"], 2)
        if on("table"):
            _, _, x_lo, x_hi = path.table_max
            self.polyline(p, [(x_lo, path.table_y), (x_hi, path.table_y)], C["table"], 3)
            self.label(p, x_lo, path.table_y, f"Tisch Y={path.table_y:.1f}", C["table"], dx=2, dy=12)
        if on("t1"):
            self.polyline(p, path.tower1, C["t1"], 1, dash=True)
        if on("t2"):
            self.polyline(p, path.tower2, C["t2"], 1, dash=True)
        for q in getattr(self, "extra", []):
            if on("t1"):
                self.polyline(p, q.tower1, C["t1"], 1, dash=True)
            if on("t2"):
                self.polyline(p, q.tower2, C["t2"], 1, dash=True)
            if on("root"):
                self.polyline(p, q.root, C["root"], 2)
            if on("tip"):
                self.polyline(p, q.tip, C["tip"], 2)
            if on("entry"):
                p.setPen(QPen(C["entry"], 2)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(self.tr(*q.entry_t1), 4, 4)
        if on("root"):
            self.polyline(p, path.root, C["root"], 2)
        if on("tip"):
            self.polyline(p, path.tip, C["tip"], 2)
        if on("faces"):
            for s_face, pts in path.faces:
                self.polyline(p, pts, C["face"], 2, dash=True)
                xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
                self.label(p, max(xs), max(ys), f"s={s_face:g}: {max(xs) - min(xs):.0f} × {max(ys) - min(ys):.1f}",
                           C["face"], dx=6, dy=4)
        if on("entry"):
            for a, b, col, key in ((path.entry_t1, path.tower1[0], C["t1"], "t1"), (path.entry_t2, path.tower2[0], C["t2"], "t2"),
                                   (path.entry_root, path.root[0], C["root"], "root"), (path.entry_tip, path.tip[0], C["tip"], "tip")):
                if on(key):
                    self.polyline(p, [a, b], col, 1, dash=True)
            p.setPen(QPen(C["entry"], 2)); p.setBrush(Qt.BrushStyle.NoBrush)
            for q, key in ((path.entry_t1, "t1"), (path.entry_t2, "t2")):
                if on(key):
                    p.drawEllipse(self.tr(*q), 4, 4)
        p.setPen(QPen(C["ref"], 2))
        o = self.tr(0, 0)
        p.drawLine(QPointF(o.x() - 8, o.y()), QPointF(o.x() + 8, o.y()))
        p.drawLine(QPointF(o.x(), o.y() - 8), QPointF(o.x(), o.y() + 8))
        if on("legend"):
            fixed = path.root_tower
            y = 30
            for key, text, col in (("root", "Wurzel" + (" (kopfüber)" if path.mirrored else ""), C["root"]),
                                   ("tip", "Ende", C["tip"]), ("faces", "Schnitt an Blockflächen", C["face"]),
                                   ("t1", "Turm 1 X/Y" + (" · Draht fest" if fixed == 1 else " · Gewicht"), C["t1"]),
                                   ("t2", "Turm 2 U/V" + (" · Draht fest" if fixed == 2 else " · Gewicht"), C["t2"]),
                                   ("block", "Block", C["block"]), ("table", "Tisch (Oberkante / max. Fläche)", C["table"])):
                if not on(key):
                    continue
                p.setPen(QPen(col, 2)); p.drawLine(QPointF(10, y), QPointF(28, y))
                p.setPen(QPen(C["text"])); p.setFont(QFont("Sans", 8)); p.drawText(QPointF(32, y + 4), text)
                y += 14


class TopView(MmCanvas):
    """Span over X: towers left/right, root/tip planes, block and table where they really are.

    Drawn with the span horizontal (the towers are 615 mm apart, the chord only
    ~200 mm), so every point goes in as (s, x): span right, machine X up.
    """

    def __init__(self, parent=None):
        super().__init__("Draufsicht   Spannrichtung →   X vorne ↑", parent)
        self.path = None

    def show_path(self, path):
        self.path = path
        if path:
            bx, by, bl, bh = path.block
            xs = [0, bx, bx + bl, path.table_max[2]] + [q[0] for q in path.tower1 + path.tower2]
            self.set_box(0, path.tower_gap, min(xs), max(xs))
        self.update()

    def draw(self, p):
        self.grid(p, with_axes=False)
        if not self.path:
            return
        path = self.path
        on = self.on
        xmin, xmax = self.box[2], self.box[3]
        for key, sv, text, col in (("t1", 0, "Turm 1 (X/Y)", C["t1"]), ("t2", path.tower_gap, "Turm 2 (U/V)", C["t2"])):
            if not on(key):
                continue
            tower = 1 if key == "t1" else 2
            text += "  Draht fest" if tower == path.root_tower else "  Gewicht"
            self.polyline(p, [(sv, xmin), (sv, xmax)], col, 3)
            self.label(p, sv, xmin, text, col, dx=6 if sv == 0 else -118, dy=14)
        bx, by, bl, bh = path.block
        if on("table"):
            t_lo, t_hi, x_lo, x_hi = path.table_max
            self.rect_mm(p, t_lo, x_lo, t_hi, max(x_hi, bx + bl), C["table"], 1, dash=True)
            self.label(p, t_lo, max(x_hi, bx + bl), "Tisch max", C["table"], dx=4, dy=-4)
        if on("block"):
            s_lo, s_hi = sorted(path.block_s)
            self.rect_mm(p, s_lo, bx, s_hi, bx + bl, C["block"], 2)
        for key, sv, pts, col, text in (("root", path.s_root, path.root, C["root"], "Wurzel"),
                                        ("tip", path.s_tip, path.tip, C["tip"], "Ende")):
            if not on(key):
                continue
            x_te, x_le = min(q[0] for q in pts), max(q[0] for q in pts)
            self.polyline(p, [(sv, x_te), (sv, x_le)], col, 3)
            self.label(p, sv, x_le, text, col, dx=-12, dy=-6)
        if on("faces"):
            for s_face, pts in path.faces:
                x_te, x_le = min(q[0] for q in pts), max(q[0] for q in pts)
                self.polyline(p, [(s_face, x_te), (s_face, x_le)], C["face"], 2, dash=True)
        if on("t1") or on("t2"):
            for pick in (min, max):
                xr = pick(q[0] for q in path.root); xt = pick(q[0] for q in path.tip)
                x1 = pick(q[0] for q in path.tower1); x2 = pick(q[0] for q in path.tower2)
                line = [(0, x1)] if on("t1") else []
                line += [(path.s_root, xr), (path.s_tip, xt)]
                if on("t2"):
                    line.append((path.tower_gap, x2))
                self.polyline(p, line, QColor("#555"), 1, dash=True)


class SimView(MmCanvas):
    """One tower of a simulation: rapids grey dashed, cuts coloured, turtle."""

    def __init__(self, title: str, colour, parent=None):
        super().__init__(title, parent)
        self.colour = colour
        self.segs: list = []
        self.upto = 0
        self.tower = 1
        self.travel = None
        self.live = None                  # where the carriage really is (from status reports)
        self.trail: list = []             # reported positions since the run started

    def load(self, segs, tower: int, travel):
        self.segs, self.tower, self.travel = segs, tower, travel
        pts = [(0.0, 0.0)] + [self._a(s) for s in segs] + [self._b(s) for s in segs]
        if travel:
            pts.append(travel)
        self.set_box(min(q[0] for q in pts), max(q[0] for q in pts), min(q[1] for q in pts), max(q[1] for q in pts))
        self.upto = 0
        self.update()

    def _a(self, s):
        return s.t1_start if self.tower == 1 else s.t2_start

    def _b(self, s):
        return s.t1_end if self.tower == 1 else s.t2_end

    def set_progress(self, upto: int):
        self.upto = max(0, min(upto, len(self.segs)))
        self.update()

    def set_live(self, pos):
        """Real carriage position; None hides it. Repeats do not grow the trail."""
        self.live = pos
        if pos is not None and (not self.trail or math.dist(self.trail[-1], pos) > 0.05):
            self.trail.append(pos)
        self.update()

    def clear_live(self):
        self.live = None; self.trail = []
        self.update()

    def draw(self, p):
        self.grid(p)
        if self.travel:
            self.rect_mm(p, 0, 0, self.travel[0], self.travel[1], C["travel"], 1, dash=True)
            self.label(p, self.travel[0], self.travel[1], "Verfahrweg", C["travel"], dx=-58, dy=12)
        for s in self.segs[self.upto:]:                     # what is still to come, faint
            if not s.rapid:
                self.polyline(p, [self._a(s), self._b(s)], C["grid"].darker(115), 1)
        for s in self.segs[:self.upto]:
            self.polyline(p, [self._a(s), self._b(s)], C["rapid"] if s.rapid else self.colour,
                          1 if s.rapid else 2, dash=s.rapid)
        if self.segs:
            if self.upto:
                s = self.segs[self.upto - 1]; q = self._b(s); on = s.wire_on
            else:
                q = self._a(self.segs[0]); on = False
            p.setPen(QPen(C["entry"], 2))
            p.setBrush(C["entry"] if on else Qt.BrushStyle.NoBrush)
            p.drawEllipse(self.tr(*q), 5, 5)
        if self.trail:
            self.polyline(p, self.trail, C["trail"], 3)
        if self.live is not None:
            o = self.tr(*self.live)
            p.setPen(QPen(C["live"], 2)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(o, 7, 7)
            p.drawLine(QPointF(o.x() - 12, o.y()), QPointF(o.x() + 12, o.y()))
            p.drawLine(QPointF(o.x(), o.y() - 12), QPointF(o.x(), o.y() + 12))
            self.label(p, self.live[0], self.live[1], f"{self.live[0]:.1f} / {self.live[1]:.1f}", C["live"], dx=10, dy=-8)
