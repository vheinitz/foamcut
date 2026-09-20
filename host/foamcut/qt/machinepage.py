"""Machine page: connection, jog pads, reference, travel, hot wire."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QRadioButton, QSlider, QVBoxLayout,
                             QWidget)

from .. import AXES
from ..jog import HORIZONTAL, STEP_SIZES, VERTICAL, JogModel
from ..machine import Machine

BIG = "font-size:14pt; font-weight:bold; padding:6px 10px;"


class MachinePage(QWidget):
    send_line = pyqtSignal(str)
    send_raw = pyqtSignal(bytes)
    connect_toggle = pyqtSignal()
    home_requested = pyqtSignal()
    set_reference = pyqtSignal()
    cut_requested = pyqtSignal(float, float, float, bool, float, float)   # length, angle, feed, back, dU, dV
    homing_dialog = pyqtSignal()

    def __init__(self, machine: Machine, model: JogModel, log, parent=None):
        super().__init__(parent)
        self.machine, self.model, self.log = machine, model, log
        v = QVBoxLayout(self)

        # ---- connection -------------------------------------------------
        top = QHBoxLayout()
        top.addWidget(QLabel("Port"))
        self.port = QLineEdit("auto"); self.port.setMaximumWidth(120)
        top.addWidget(self.port)
        self.b_conn = QPushButton("Verbinden"); self.b_conn.clicked.connect(self.connect_toggle)
        top.addWidget(self.b_conn)
        top.addStretch()
        self.pins = QLabel(""); self.pins.setStyleSheet("color:#b00; font-size:13pt; font-weight:bold;")
        top.addWidget(self.pins)
        self.state = QLabel("nicht verbunden"); self.state.setStyleSheet("font-size:14pt; font-weight:bold; min-width:120px;")
        top.addWidget(self.state)
        v.addLayout(top)

        # ---- position ---------------------------------------------------
        posbox = QGroupBox("Position (Arbeitskoordinaten, 0 = Referenz)")
        pl = QHBoxLayout(posbox)
        self.pos = {}
        for a in AXES:
            pl.addWidget(QLabel(a)); lab = QLabel("—"); lab.setStyleSheet("font-family:monospace; font-size:13pt; min-width:90px;")
            lab.setAlignment(Qt.AlignmentFlag.AlignRight); self.pos[a] = lab; pl.addWidget(lab); pl.addSpacing(20)
        pl.addStretch()
        v.addWidget(posbox)

        # ---- step + feeds ----------------------------------------------
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("Schritt"))
        self.steps = QButtonGroup(self)
        for s in STEP_SIZES:
            rb = QRadioButton(f"{s:g} mm"); rb.setChecked(s == model.step)
            self.steps.addButton(rb); ctl.addWidget(rb)
            rb.toggled.connect(lambda on, s=s: on and setattr(model, "step", s))
        ctl.addSpacing(20)
        self.feed_h = self._feed(ctl, "waagerecht X/U", "feed_h", min(machine.max_rate[a] for a in HORIZONTAL))
        self.feed_v = self._feed(ctl, "senkrecht Y/V", "feed_v", min(machine.max_rate[a] for a in VERTICAL))
        ctl.addStretch()
        v.addLayout(ctl)

        # ---- pads -------------------------------------------------------
        pads = QHBoxLayout()
        pads.addWidget(self._pad("Turm 1  (X / Y)", "X", "Y"))
        pads.addWidget(self._both())
        pads.addWidget(self._pad("Turm 2  (U / V)", "U", "V"))
        v.addLayout(pads)

        # ---- actions ----------------------------------------------------
        act = QHBoxLayout()
        b = QPushButton("STOP"); b.setStyleSheet("font-weight:bold; color:#b00;"); b.clicked.connect(lambda: self.send_raw.emit(b"\x85")); act.addWidget(b)
        b = QPushButton("$X entsperren"); b.clicked.connect(lambda: self.send_line.emit("$X")); act.addWidget(b)
        b = QPushButton("Reset"); b.clicked.connect(lambda: self.send_raw.emit(b"\x18")); act.addWidget(b)
        act.addSpacing(16)
        self.b_home = QPushButton("Referenzfahrt ($H)"); self.b_home.clicked.connect(self.home_requested)
        self.b_home.setEnabled(machine.homing.enabled); act.addWidget(self.b_home)
        b = QPushButton("Endschalter…"); b.clicked.connect(self.homing_dialog); act.addWidget(b)
        b = QPushButton("Referenz hier setzen (0/0/0/0)"); b.clicked.connect(self.set_reference); act.addWidget(b)
        b = QPushButton("zur Referenz"); b.clicked.connect(lambda: self.send_line.emit(model.goto_reference())); act.addWidget(b)
        act.addSpacing(16); act.addWidget(QLabel("Verfahrweg = hier:"))
        for a in AXES:
            b = QPushButton(a); b.setMaximumWidth(32); b.clicked.connect(lambda _, a=a: self.save_travel(a)); act.addWidget(b)
        act.addStretch()
        v.addLayout(act)

        # ---- hot wire ---------------------------------------------------
        wire = QGroupBox("Heizdraht")
        wl = QHBoxLayout(wire)
        self.power = QSlider(Qt.Orientation.Horizontal); self.power.setRange(0, 255); self.power.setValue(machine.wire_power or 0)
        self.power_lbl = QLabel(f"S{self.power.value()}"); self.power_lbl.setMinimumWidth(48)
        self.power.valueChanged.connect(lambda val: self.power_lbl.setText(f"S{val}"))
        wl.addWidget(self.power, 1); wl.addWidget(self.power_lbl)
        b = QPushButton("Draht AN"); b.clicked.connect(lambda: self.send_line.emit(model.hotwire(self.power.value()))); wl.addWidget(b)
        b = QPushButton("Draht AUS"); b.clicked.connect(lambda: self.send_line.emit("M5")); wl.addWidget(b)
        v.addWidget(wire)

        # ---- straight cut from the current position --------------------------
        cut = QGroupBox("Freischnitt: hinfahren, dann gerade schneiden")
        cl = QHBoxLayout()
        cl.addWidget(QLabel("Länge"))
        self.cut_len = QLineEdit("100"); self.cut_len.setMaximumWidth(70); self.cut_len.setAlignment(Qt.AlignmentFlag.AlignRight)
        cl.addWidget(self.cut_len); cl.addWidget(QLabel("mm   Vorschub"))
        self.cut_feed = QLineEdit(f"{machine.cut_feed:g}"); self.cut_feed.setMaximumWidth(70); self.cut_feed.setAlignment(Qt.AlignmentFlag.AlignRight)
        cl.addWidget(self.cut_feed); cl.addWidget(QLabel("mm/min"))
        self.cut_back = QCheckBox("und zurück"); cl.addWidget(self.cut_back)
        cl.addSpacing(12)
        for text, angle in (("→ vor", 0.0), ("← zurück", 180.0), ("↑ hoch", 90.0), ("↓ runter", 270.0)):
            b = QPushButton(text); b.clicked.connect(lambda _, a=angle: self._cut(a)); cl.addWidget(b)
        cl.addSpacing(12); cl.addWidget(QLabel("Winkel"))
        self.cut_angle = QLineEdit("0"); self.cut_angle.setMaximumWidth(50); self.cut_angle.setAlignment(Qt.AlignmentFlag.AlignRight)
        cl.addWidget(self.cut_angle); cl.addWidget(QLabel("°"))
        b = QPushButton("schräg"); b.clicked.connect(lambda: self._cut(None)); cl.addWidget(b)
        cl.addStretch()
        skew = QHBoxLayout(); cut_v = QVBoxLayout(cut); cut_v.addLayout(cl); cut_v.addLayout(skew)
        v.addWidget(cut)
        skew.addWidget(QLabel("Turm 2 versetzt:  U"))
        self.skew_u = QLineEdit("0"); self.skew_u.setMaximumWidth(60); self.skew_u.setAlignment(Qt.AlignmentFlag.AlignRight)
        skew.addWidget(self.skew_u); skew.addWidget(QLabel("mm  (Pfeilung mit ↑/↓, Winkel = atan(U / Turmabstand))    V"))
        self.skew_v = QLineEdit("0"); self.skew_v.setMaximumWidth(60); self.skew_v.setAlignment(Qt.AlignmentFlag.AlignRight)
        skew.addWidget(self.skew_v); skew.addWidget(QLabel("mm  (schiefe Ebene mit →/←)"))
        self.skew_lbl = QLabel(""); skew.addWidget(self.skew_lbl)
        for w in (self.skew_u, self.skew_v):
            w.textChanged.connect(self._skew_changed)
        skew.addStretch()
        v.addStretch()

    def _feed(self, layout, label, attr, maximum):
        layout.addWidget(QLabel(label))
        sb = QDoubleSpinBox(); sb.setRange(10, maximum); sb.setSingleStep(10); sb.setDecimals(0)
        sb.setValue(min(getattr(self.model, attr), maximum))
        sb.valueChanged.connect(lambda val: setattr(self.model, attr, val))
        layout.addWidget(sb); layout.addWidget(QLabel(f"mm/min (max {maximum:g})"))
        return sb

    def _btn(self, text, moves):
        b = QPushButton(text); b.setStyleSheet(BIG)
        b.clicked.connect(lambda: self.send_line.emit(self.model.jog(moves)))
        return b

    def _pad(self, title, h, v):
        box = QGroupBox(title); g = QGridLayout(box)
        g.addWidget(self._btn(f"▲ {v}+", {v: +1}), 0, 1)
        g.addWidget(self._btn(f"◀ {h}−", {h: -1}), 1, 0)
        lab = QLabel("hinten ◀ ▶ vorne"); lab.setAlignment(Qt.AlignmentFlag.AlignCenter); g.addWidget(lab, 1, 1)
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

    def save_travel(self, axis):
        val = self.model.record_travel(axis)
        self.machine.save()
        self.log(f"Verfahrweg {axis} = {val:g} mm gespeichert")

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
            feed = float(self.cut_feed.text().replace(",", "."))
            du, dv = self._skew()
            if angle is None:
                angle = float(self.cut_angle.text().replace(",", "."))
        except ValueError:
            self.log("! Freischnitt: Länge, Vorschub, Winkel und Versatz müssen Zahlen sein"); return
        if length <= 0 or feed <= 0:
            self.log("! Freischnitt: Länge und Vorschub müssen > 0 sein"); return
        self.machine.cut_feed = feed
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
