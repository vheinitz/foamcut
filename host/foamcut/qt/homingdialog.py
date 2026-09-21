"""Endschalter calibration dialog (Qt). Same flow as the Tk one."""
from __future__ import annotations

import queue

from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton

from .. import AXES
from ..machine import Machine
from .uiload import load_ui

HINT = "color:#666; font-size:9pt;"


class HomingDialog(QDialog):
    def __init__(self, machine: Machine, get_worker, log, on_saved, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Endschalter")
        self.machine, self.get_worker, self.log, self.on_saved = machine, get_worker, log, on_saved
        h = machine.homing
        load_ui("homingdialog", self)
        self.enabled.setChecked(h.enabled)
        (self.nc if h.invert_switch else self.no).setChecked(True)
        self.pulloff.setText(f"{h.pulloff:g}"); self.seek.setText(f"{h.seek:g}"); self.feed.setText(f"{h.feed:g}")
        # one row per axis: offset (+ take-current button) and length from the switch
        g = self.axes_grid
        g.addWidget(self._hint("Versatz: so weit in + liegt der Arbeitsnullpunkt hinter der Schalterposition - z.B. um den Draht waagerecht zu stellen. "
                               "Länge: nutzbarer Weg ab Schalter, von Hand eingegeben. Die Suchfahrt läuft bis 1,5× Länge."), 0, 0, 1, 4)
        for col, text in enumerate(("Achse", "Versatz + [mm]", "", "Länge ab Schalter [mm]")):
            g.addWidget(QLabel(text), 1, col)
        names = {"X": "X  Turm 1 waagerecht", "Y": "Y  Turm 1 senkrecht", "U": "U  Turm 2 waagerecht", "V": "V  Turm 2 senkrecht"}
        self.off = {}; self.len = {}
        for r, a in enumerate(AXES, start=2):
            g.addWidget(QLabel(names[a]), r, 0)
            self.off[a] = QLineEdit(f"{h.offset_mm[a]:g}"); self.off[a].setMaximumWidth(80); g.addWidget(self.off[a], r, 1)
            b = QPushButton("= aktuelle Position"); b.clicked.connect(lambda _, a=a: self.take_current(a)); g.addWidget(b, r, 2)
            self.len[a] = QLineEdit(f"{h.length_mm[a]:g}"); self.len[a].setMaximumWidth(80); g.addWidget(self.len[a], r, 3)
        self.b_pins.clicked.connect(self.read_pins)
        self.b_home.clicked.connect(self.do_home); self.b_close.clicked.connect(self.close); self.b_save.clicked.connect(self.save)

    def _hint(self, text):
        lab = QLabel(text); lab.setWordWrap(True); lab.setStyleSheet(HINT); return lab

    def _probe(self, kind):
        w = self.get_worker()
        if not w:
            self.status.setText("nicht verbunden"); return None
        got = queue.Queue(); w.submit(kind, got)
        try:
            return got.get(timeout=3)
        except queue.Empty:
            self.status.setText("keine Antwort vom Board"); return None

    def read_pins(self):
        st = self._probe("probe_status")
        if st is None:
            return
        pressed = [c for c in st.get("pn", "") if c in AXES]
        self.pins.setText(("gedrückt: " + " ".join(pressed)) if pressed else "kein Schalter gedrückt")

    def take_current(self, axis):
        h = self.machine.homing
        if not h.home_mpos:
            self.status.setText("erst Referenzfahrt, dann Position übernehmen"); return
        mpos = self._probe("probe_pos")
        if mpos is None:
            return
        self.off[axis].setText(f"{mpos[axis] - h.home_mpos[axis]:.3f}")
        self.status.setText(f"{axis}: Versatz {self.off[axis].text()} mm = aktuelle Position minus Schalter")

    def read_form(self) -> list[str]:
        errors = []
        def num(w, name, lo):
            try:
                v = float(w.text().replace(",", "."))
            except ValueError:
                errors.append(f"{name}: keine Zahl"); return None
            if v < lo:
                errors.append(f"{name}: muss >= {lo:g} sein")
            return v
        h = self.machine.homing
        h.enabled = self.enabled.isChecked(); h.invert_switch = self.nc.isChecked()
        p = num(self.pulloff, "Pull-off", 0.5); s = num(self.seek, "Suchgeschwindigkeit", 10); f = num(self.feed, "Referenzgeschwindigkeit", 5)
        offs = {a: num(self.off[a], f"Versatz {a}", 0.0) for a in AXES}
        lens = {a: num(self.len[a], f"Länge {a}", 0.0) for a in AXES}
        if errors:
            return errors
        h.pulloff, h.seek, h.feed = p, s, f
        h.offset_mm.update(offs); h.length_mm.update(lens)
        if h.enabled and any(h.length_mm[a] <= 0 for a in AXES):
            errors.append("Länge ab Schalter fehlt für mindestens eine Achse")
        return errors

    def do_home(self):
        errs = self.read_form()
        if errs:
            self.status.setText("\n".join(errs)); return
        w = self.get_worker()
        if not w:
            self.status.setText("nicht verbunden"); return
        if not self.machine.homing.enabled:
            self.status.setText("Endschalter zuerst aktivieren"); return
        self.machine.save(); self.on_saved(); w.submit("home")
        self.status.setText("Referenzfahrt läuft - siehe Log")

    def save(self):
        errs = self.read_form()
        if errs:
            self.status.setText("\n".join(errs)); return
        self.machine.save(); self.on_saved()
        w = self.get_worker(); h = self.machine.homing
        if w and h.enabled and h.home_mpos:
            origin = h.work_origin(h.home_mpos)
            w.submit("line", "G10 L2 P1 " + " ".join(f"{a}{origin[a]:.3f}" for a in AXES)); w.submit("line", "G54"); w.submit("offset")
        self.status.setText("gespeichert.  nutzbar: " + "  ".join(f"{a} {h.usable_travel(a):.1f}" for a in AXES))
        self.log("Endschalter-Konfiguration gespeichert" + (" (aktiv)" if h.enabled else " (aus)"))
