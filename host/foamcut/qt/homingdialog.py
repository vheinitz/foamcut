"""Endschalter calibration dialog (Qt). Same flow as the Tk one."""
from __future__ import annotations

import queue

from PyQt6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QRadioButton, QVBoxLayout)

from .. import AXES
from ..machine import Machine

HINT = "color:#666; font-size:9pt;"


class HomingDialog(QDialog):
    def __init__(self, machine: Machine, get_worker, log, on_saved, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Endschalter")
        self.machine, self.get_worker, self.log, self.on_saved = machine, get_worker, log, on_saved
        h = machine.homing
        v = QVBoxLayout(self)

        self.enabled = QCheckBox("Endschalter verwenden (Referenzfahrt statt Ecke von Hand)"); self.enabled.setChecked(h.enabled)
        v.addWidget(self.enabled)
        v.addWidget(self._hint("Alle vier Schalter am negativen Ende: X/U hinten, Y/V unten. Verdrahtung: X an X_MIN, Y an X_MAX, "
                               "U an Y_MIN, V an Y_MAX (Öffner zwischen S und GND), siehe docs/gt2560_pinout.md. Beim Verbinden "
                               "läuft die Referenzfahrt automatisch; gedrückte Schalter werden vorher 5 mm freigefahren."))

        sw = QGroupBox("Schalterart"); sl = QVBoxLayout(sw)
        self.no = QRadioButton("Schließer (NO): offen, bis er gedrückt wird")
        self.nc = QRadioButton("Öffner (NC): geschlossen, öffnet beim Drücken - sicherer bei Kabelbruch (Umkehr ist in der Firmware fest, $5 bleibt 0)")
        (self.nc if h.invert_switch else self.no).setChecked(True)
        sl.addWidget(self.no); sl.addWidget(self.nc)
        v.addWidget(sw)

        fahrt = QGroupBox("Fahrt"); fl = QFormLayout(fahrt)
        self.pulloff = QLineEdit(f"{h.pulloff:g}"); self.seek = QLineEdit(f"{h.seek:g}"); self.feed = QLineEdit(f"{h.feed:g}")
        for w in (self.pulloff, self.seek, self.feed):
            w.setMaximumWidth(80)
        fl.addRow("Pull-off [mm]", self.pulloff)
        fl.addRow("", self._hint("So weit fährt jede Achse nach dem Auslösen wieder vom Schalter weg; dort ist die Maschinenposition 'Schalter'."))
        fl.addRow("Suchgeschwindigkeit [mm/min]", self.seek)
        fl.addRow("Referenzgeschwindigkeit [mm/min]", self.feed)
        fl.addRow("", self._hint("Erste schnelle, dann langsame Anfahrt; die zweite bestimmt die Wiederholgenauigkeit."))
        v.addWidget(fahrt)

        ax = QGroupBox("Achsen"); g = QGridLayout(ax)
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
        v.addWidget(ax)

        pr = QHBoxLayout()
        b = QPushButton("Schalterzustand lesen"); b.clicked.connect(self.read_pins); pr.addWidget(b)
        self.pins = QLabel(""); pr.addWidget(self.pins, 1)
        v.addLayout(pr)
        v.addWidget(self._hint("Jeden Schalter von Hand drücken und lesen: genau die richtige Achse muss erscheinen. Erscheint sie losgelassen, ist die Schalterart falsch herum."))
        self.status = QLabel(""); self.status.setStyleSheet("color:#b00;"); self.status.setWordWrap(True); v.addWidget(self.status)

        bar = QHBoxLayout()
        b = QPushButton("Referenzfahrt jetzt ($H)"); b.clicked.connect(self.do_home); bar.addWidget(b)
        bar.addStretch()
        b = QPushButton("Schließen"); b.clicked.connect(self.close); bar.addWidget(b)
        b = QPushButton("Speichern & aufs Board"); b.setDefault(True); b.clicked.connect(self.save); bar.addWidget(b)
        v.addLayout(bar)

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
