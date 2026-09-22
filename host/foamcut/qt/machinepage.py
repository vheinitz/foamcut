"""Machine page: connection, jog pads, reference, travel, hot wire."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QGridLayout, QGroupBox, QLabel, QPushButton, QRadioButton, QSizePolicy, QWidget

from .. import AXES
from .uiload import load_ui
from ..jog import HORIZONTAL, STEP_SIZES, VERTICAL, JogModel
from ..machine import Machine

BIG = "font-size:12pt; font-weight:bold; padding:3px 4px;"


class MachinePage(QWidget):
    send_line = pyqtSignal(str)
    send_raw = pyqtSignal(bytes)
    connect_toggle = pyqtSignal()
    home_requested = pyqtSignal()
    set_reference = pyqtSignal()
    cut_requested = pyqtSignal(float, float, float, bool, float, float)   # length, angle, feed, back, dU, dV
    homing_dialog = pyqtSignal()
    machine_changed = pyqtSignal()      # kerf etc. edited here: design pages regenerate

    def __init__(self, machine: Machine, model: JogModel, log, parent=None):
        super().__init__(parent)
        self.machine, self.model, self.log = machine, model, log
        load_ui("machinepage", self)
        self.b_conn.clicked.connect(self.connect_toggle)
        # position labels, one per axis
        self.pos = {}
        for a in AXES:
            self.pos_layout.addWidget(QLabel(a))
            lab = QLabel("—"); lab.setStyleSheet("font-family:monospace; font-size:13pt; min-width:80px;")
            lab.setAlignment(Qt.AlignmentFlag.AlignRight); self.pos[a] = lab; self.pos_layout.addWidget(lab)
            self.pos_layout.addSpacing(12)
        self.pos_layout.addStretch()
        # step sizes + feeds
        self.steps = QButtonGroup(self)
        for st in STEP_SIZES:
            rb = QRadioButton(f"{st:g} mm"); rb.setChecked(st == model.step)
            self.steps.addButton(rb); self.steps_layout.addWidget(rb)
            rb.toggled.connect(lambda on, st=st: on and setattr(model, "step", st))
        self._feed(self.feed_h, self.feed_h_max, "feed_h", min(machine.max_rate[a] for a in HORIZONTAL))
        self._feed(self.feed_v, self.feed_v_max, "feed_v", min(machine.max_rate[a] for a in VERTICAL))
        # jog pads
        self.pads_layout.addWidget(self._pad("Turm 1  (X / Y)", "X", "Y"))
        self.pads_layout.addWidget(self._both())
        self.pads_layout.addWidget(self._pad("Turm 2  (U / V)", "U", "V"))
        # actions
        self.b_stop.clicked.connect(lambda: self.send_raw.emit(b"\x85"))
        self.b_unlock.clicked.connect(lambda: self.send_line.emit("$X"))
        self.b_reset.clicked.connect(lambda: self.send_raw.emit(b"\x18"))
        self.b_home.clicked.connect(self.home_requested); self.b_home.setEnabled(machine.homing.enabled)
        self.b_homing.clicked.connect(self.homing_dialog)
        self.b_ref.clicked.connect(self.set_reference)
        self.b_goto.clicked.connect(lambda: self.send_line.emit(model.goto_reference()))
        for a in AXES:
            b = QPushButton(a); b.setMaximumWidth(32); b.clicked.connect(lambda _, a=a: self.save_travel(a))
            self.travel_layout.addWidget(b)
        # hot wire
        self.power.setValue(machine.wire_power or 0); self.power_lbl.setText(f"S{self.power.value()}")
        self.power.valueChanged.connect(lambda val: self.power_lbl.setText(f"S{val}"))
        self.b_wire_on.clicked.connect(lambda: self.send_line.emit(model.hotwire(self.power.value())))
        self.b_wire_off.clicked.connect(lambda: self.send_line.emit("M5"))
        # cut settings live in machine.json - one set for every generator
        for w, attr in ((self.cut_feed, "cut_feed"), (self.warmup, "warmup_s"), (self.kerf, "kerf_mm")):
            w.setText(f"{getattr(machine, attr):g}")
            w.editingFinished.connect(lambda w=w, attr=attr: self._cut_setting(w, attr))
        self.power.sliderReleased.connect(self._power_changed)
        # machine geometry: it belongs here, not on every design page
        self.gap.setText(f"{machine.tower_gap_mm:g}"); self.gap.editingFinished.connect(self._gap_changed)
        self.fixed.addItems(["Turm 1 (X/Y)", "Turm 2 (U/V)"])
        self.fixed.setCurrentIndex(0 if machine.wire_fixed_tower == 1 else 1)
        self.fixed.currentIndexChanged.connect(self._fixed_changed)
        self.show_travel()
        # straight cut
        for b, angle in ((self.b_cut_fwd, 0.0), (self.b_cut_back, 180.0), (self.b_cut_up, 90.0), (self.b_cut_down, 270.0)):
            b.clicked.connect(lambda _, a=angle: self._cut(a))
        self.b_cut_angle.clicked.connect(lambda: self._cut(None))
        for w in (self.skew_u, self.skew_v):
            w.textChanged.connect(self._skew_changed)

    def _feed(self, sb, max_lbl, attr, maximum):
        sb.setRange(10, maximum)
        sb.setValue(min(getattr(self.model, attr), maximum))
        sb.valueChanged.connect(lambda val: setattr(self.model, attr, val))
        max_lbl.setText(f"mm/min (max {maximum:g})")

    def _btn(self, text, moves):
        b = QPushButton(text); b.setStyleSheet(BIG)
        # Ignored: the label width does not dictate the window width; the pads
        # share whatever is there, down to this floor
        b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); b.setMinimumWidth(56)
        b.clicked.connect(lambda: self.send_line.emit(self.model.jog(moves)))
        return b

    def _pad(self, title, h, v):
        box = QGroupBox(title); g = QGridLayout(box)
        g.addWidget(self._btn(f"▲ {v}+", {v: +1}), 0, 1)
        g.addWidget(self._btn(f"◀ {h}−", {h: -1}), 1, 0)
        lab = QLabel("hinten ◀ ▶ vorne"); lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); g.addWidget(lab, 1, 1)
        g.addWidget(self._btn(f"{h}+ ▶", {h: +1}), 1, 2)
        g.addWidget(self._btn(f"▼ {v}−", {v: -1}), 2, 1)
        return box

    def _both(self):
        box = QGroupBox("beide Türme"); g = QGridLayout(box)
        g.addWidget(self._btn("▲ Y+V+", {"Y": +1, "V": +1}), 0, 1)
        g.addWidget(self._btn("◀ X−U−", {"X": -1, "U": -1}), 1, 0)
        g.addWidget(self._btn("X+U+ ▶", {"X": +1, "U": +1}), 1, 2)
        g.addWidget(self._btn("▼ Y−V−", {"Y": -1, "V": -1}), 2, 1)
        return box

    def _cut_setting(self, w, attr):
        try:
            val = float(w.text().replace(",", "."))
            if val < 0 or (attr == "cut_feed" and val <= 0):
                raise ValueError
        except ValueError:
            self.log(f"! {attr}: keine gueltige Zahl"); w.setText(f"{getattr(self.machine, attr):g}"); return
        if val != getattr(self.machine, attr):
            setattr(self.machine, attr, val); self.machine.save()
            self.log(f"{attr} = {val:g} gespeichert (machine.json)"); self.machine_changed.emit()

    def show_travel(self):
        t = self.machine.travel_mm
        self.travel_show.setText("   Verfahrweg " + " ".join(f"{a} {t[a]:g}" for a in AXES) + " mm"
                                 + ("" if self.machine.tower_gap_measured else "   TURMABSTAND NICHT GEMESSEN"))

    def _gap_changed(self):
        try:
            val = float(self.gap.text().replace(",", "."))
            if val <= 0:
                raise ValueError
        except ValueError:
            self.log("! Turmabstand muss eine Zahl > 0 sein"); self.gap.setText(f"{self.machine.tower_gap_mm:g}"); return
        if abs(val - self.machine.tower_gap_mm) > 1e-9:
            self.machine.tower_gap_mm = val; self.machine.tower_gap_measured = True
            self.machine.save(); self.show_travel()
            self.log(f"Turmabstand {val:g} mm gespeichert"); self.machine_changed.emit()

    def _fixed_changed(self):
        tower = self.fixed.currentIndex() + 1
        if tower != self.machine.wire_fixed_tower:
            self.machine.wire_fixed_tower = tower; self.machine.save()
            self.log(f"Draht fest an Turm {tower} gespeichert"); self.machine_changed.emit()

    def _power_changed(self):
        if self.power.value() != self.machine.wire_power:
            self.machine.wire_power = self.power.value(); self.machine.save(); self.machine_changed.emit()

    def save_travel(self, axis):
        val = self.model.record_travel(axis)
        self.machine.save(); self.show_travel()
        self.log(f"Verfahrweg {axis} = {val:g} mm gespeichert")
        self.machine_changed.emit()

    # ---- updates from the worker ----------------------------------------
    def _skew(self) -> tuple[float, float]:
        return (float(self.skew_u.text().replace(",", ".") or 0), float(self.skew_v.text().replace(",", ".") or 0))

    def _skew_changed(self, *_):
        import math
        try:
            du, dv = self._skew()
        except ValueError:
            self.skew_lbl.setText("?"); return
        gap = self.machine.tower_gap_mm
        self.skew_lbl.setText(f"→ {math.degrees(math.atan2(du, gap)):.1f}° Pfeilung, {math.degrees(math.atan2(dv, gap)):.1f}° Neigung")

    def _cut(self, angle):
        """Winkel: 0 = vor, 90 = hoch, 180 = zurück, 270 = runter; None = Feld."""
        try:
            length = float(self.cut_len.text().replace(",", "."))
            feed = self.machine.cut_feed
            du, dv = self._skew()
            if angle is None:
                angle = float(self.cut_angle.text().replace(",", "."))
        except ValueError:
            self.log("! Freischnitt: Länge, Winkel und Versatz müssen Zahlen sein"); return
        if length <= 0:
            self.log("! Freischnitt: Länge muss > 0 sein"); return
        self.cut_requested.emit(length, angle, feed, self.cut_back.isChecked(), du, dv)

    def show_status(self, st: dict, wpos: dict):
        self.state.setText(st["state"])
        for a in AXES:
            self.pos[a].setText(f"{wpos[a]:.3f}")
        pressed = [c for c in st.get("pn", "") if c in AXES]
        self.pins.setText(("Endschalter: " + " ".join(pressed)) if pressed else "")

    def unknown_position(self):
        for a in AXES:
            self.pos[a].setText("?")
