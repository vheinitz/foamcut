"""Design page (wings, free shapes): steps on the left, live drawing on the
right, warnings inline. Which fields, parser and generator it drives comes
from a wing.Model."""
from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QPushButton, QRadioButton, QScrollArea,
                             QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from .. import gcode as gc
from ..machine import Machine
from ..wing import WING_MODEL, Model, WingError, field_catalogue
from .canvas import LAYERS, FrontView, TopView
from .state import UiState

WARN_STYLE = "background:#fff4d6; border:1px solid #e0c070; padding:4px 8px; border-radius:4px;"
ERR_STYLE = "background:#ffd9d9; border:1px solid #e08080; padding:4px 8px; border-radius:4px;"
OK_STYLE = "background:#e4f5e4; border:1px solid #8fd19e; padding:4px 8px; border-radius:4px;"


class DesignPage(QWidget):
    gcode_ready = pyqtSignal(str, str)          # (gcode text, name)

    def __init__(self, machine: Machine, airfoil_dir: Path, state: UiState, log, parent=None,
                 model: Model = WING_MODEL):
        super().__init__(parent)
        self.machine, self.airfoil_dir, self.state, self.log = machine, airfoil_dir, state, log
        self.model = model
        self.inputs: dict[str, QWidget] = {}
        self.spec = None
        self.path = None
        self.gcode = ""
        self.sent = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.rebuild)

        airfoils = sorted(p.name for p in airfoil_dir.glob("*.dat")) if airfoil_dir.exists() else []
        saved = state.get(model.key, {})
        cat = field_catalogue(model.fields)

        # ---- left: step list + stacked forms ---------------------------
        self.nav = QListWidget()
        self.nav.setFixedWidth(150)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stack = QStackedWidget()
        for section, title, fields in model.fields + [("machine", "Maschine", [])]:
            self.nav.addItem(title)
            page = QWidget()
            form = QFormLayout(page)
            form.setVerticalSpacing(2)
            if section == "machine":
                self._machine_form(form)
            for key, label, unit, default, help_, kind in fields:
                value = saved.get(key, default)
                if kind == "airfoil":
                    w = QComboBox(); w.setEditable(True); w.addItems([""] + airfoils)
                    w.setCurrentText(value)
                    w.currentTextChanged.connect(self.schedule)
                elif kind.startswith("choice:"):
                    w = QComboBox(); w.addItems(kind.split(":", 1)[1].split("|"))
                    w.setCurrentText(value)
                    w.currentTextChanged.connect(self.schedule)
                elif kind == "bool":
                    w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
                    w.nein = QRadioButton("nein"); w.ja = QRadioButton("ja")
                    (w.ja if value == "ja" else w.nein).setChecked(True)
                    h.addWidget(w.nein); h.addWidget(w.ja); h.addStretch()
                    w.ja.toggled.connect(self.schedule)
                else:
                    w = QLineEdit(str(value)); w.setMaximumWidth(90)
                    w.setAlignment(Qt.AlignmentFlag.AlignRight)
                    w.textChanged.connect(self.schedule)
                self.inputs[key] = w
                row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0)
                rl.addWidget(w)
                if unit:
                    rl.addWidget(QLabel(unit))
                rl.addStretch()
                form.addRow(label, row)
                hint = QLabel(help_); hint.setWordWrap(True)
                hint.setStyleSheet("color:#666; font-size:9pt; margin-bottom:6px;")
                form.addRow("", hint)
            if section == "block":
                self._block_form(form)
            scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(page)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.stack.addWidget(scroll)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        # ---- right: layer toggles, drawings, result -------------------------
        self.front = FrontView()
        self.top = TopView()
        shown = state.get(f"{model.key}_layers", {})
        layer_bar = QHBoxLayout(); layer_bar.setSpacing(10)
        layer_bar.addWidget(QLabel("Einblenden:"))
        self.layer_boxes: dict[str, QCheckBox] = {}
        for key, text in LAYERS:
            box = QCheckBox(text); box.setChecked(bool(shown.get(key, True)))
            box.toggled.connect(self._layers_changed)
            layer_bar.addWidget(box); self.layer_boxes[key] = box
        layer_bar.addStretch()
        self._layers_changed()
        self.messages = QVBoxLayout()
        self.messages.setSpacing(3)
        msg_box = QWidget(); msg_box.setLayout(self.messages)
        self.result = QLabel(""); self.result.setStyleSheet("font-family:monospace; font-size:9pt;")
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(layer_bar)
        views = QSplitter(Qt.Orientation.Vertical)
        views.addWidget(self.front); views.addWidget(self.top)
        views.setSizes([460, 220])
        rv.addWidget(views, 1)
        rv.addWidget(msg_box)
        rv.addWidget(self.result)

        # ---- bottom bar ------------------------------------------------
        bar = QHBoxLayout()
        b_load = QPushButton("Laden…"); b_load.clicked.connect(self.load_spec)
        b_save = QPushButton("Speichern…"); b_save.clicked.connect(self.save_spec)
        self.b_prog = QPushButton("→ Programm"); self.b_prog.clicked.connect(self.to_program)
        b_gc = QPushButton("G-Code speichern…"); b_gc.clicked.connect(self.save_gcode)
        self.stale = QLabel(""); self.stale.setStyleSheet("color:#b00; font-weight:bold;")
        bar.addWidget(b_load); bar.addWidget(b_save); bar.addSpacing(16); bar.addWidget(self.stale)
        bar.addStretch(); bar.addWidget(b_gc); bar.addWidget(self.b_prog)

        left = QWidget(); lv = QHBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.nav); lv.addWidget(self.stack, 1)
        split = QSplitter(); split.addWidget(left); split.addWidget(right)
        split.setSizes([620, 760])
        outer = QVBoxLayout(self); outer.addWidget(split, 1); outer.addLayout(bar)
        QTimer.singleShot(0, self.rebuild)

    # ---- machine step (tower gap) ------------------------------------------
    def _machine_form(self, form: QFormLayout):
        self.gap = QLineEdit(f"{self.machine.tower_gap_mm:g}"); self.gap.setMaximumWidth(90)
        self.gap.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.gap.textChanged.connect(self.schedule)
        row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.gap); rl.addWidget(QLabel("mm")); rl.addStretch()
        form.addRow("Turmabstand", row)
        hint = QLabel("Abstand der beiden Drahtaufhängungen (Schlittenebenen), mit dem Maßband gemessen. "
                      "Wird in machine.json gespeichert." +
                      ("" if self.machine.tower_gap_measured else "  NOCH NICHT GEMESSEN - Platzhalter!"))
        hint.setWordWrap(True); hint.setStyleSheet("color:#666; font-size:9pt;")
        form.addRow("", hint)
        self.fixed = QComboBox(); self.fixed.addItems(["Turm 1 (X/Y)", "Turm 2 (U/V)"])
        self.fixed.setCurrentIndex(0 if self.machine.wire_fixed_tower == 1 else 1)
        self.fixed.currentIndexChanged.connect(self.schedule)
        form.addRow("Draht fest an", self.fixed)
        hint2 = QLabel("An diesem Turm ist der Heizdraht fest eingespannt; am anderen zieht das Gewicht über "
                       "die Rolle. Nur das feste Ende ist ein genauer Bezug, deshalb liegt die Flügelwurzel "
                       "immer dort. Wird in machine.json gespeichert.")
        hint2.setWordWrap(True); hint2.setStyleSheet("color:#666; font-size:9pt; margin-bottom:6px;")
        form.addRow("", hint2)
        for a in ("X", "Y", "U", "V"):
            form.addRow(f"Verfahrweg {a}", QLabel(f"{self.machine.travel_mm[a]:g} mm   (Endschalter / Verfahrweg-Dialog)"))

    # ---- block step (minimal block) -------------------------------------------
    def _block_form(self, form: QFormLayout):
        self.b_minblock = QPushButton("Mindestblock übernehmen")
        self.b_minblock.clicked.connect(self.apply_min_block)
        form.addRow("", self.b_minblock)
        self.minblock_hint = QLabel("")
        self.minblock_hint.setWordWrap(True); self.minblock_hint.setStyleSheet("color:#666; font-size:9pt;")
        form.addRow("", self.minblock_hint)
        self.b_table = QPushButton("Tisch so tief wie möglich")
        self.b_table.clicked.connect(self.lowest_table)
        form.addRow("", self.b_table)
        self.table_hint = QLabel("")
        self.table_hint.setWordWrap(True); self.table_hint.setStyleSheet("color:#666; font-size:9pt;")
        form.addRow("", self.table_hint)

    def lowest_table(self):
        """Put the table (and with it the profile) as low as the carriages allow."""
        self.rebuild()
        if not self.path:
            return
        lo = math.ceil(self.path.table_range[0])
        self.set_values({"table_y": f"{lo:g}"})
        self.rebuild()
        self.log(f"Tischoberkante auf Y={lo:g} gesetzt (Minimum)")

    def apply_min_block(self):
        """Fill the block fields with the smallest block that holds the cut (Rand from Schnitt)."""
        self.rebuild()
        if not self.path:
            return
        bx, by, bl, bh, start, width = self.path.min_block
        self.set_values({"block_s": f"{start:g}", "block_w": f"{width:.0f}", "block_len": f"{bl:.0f}",
                         "block_h": f"{bh:.0f}"})
        self.rebuild()
        self.log(f"Block gesetzt: {bl:.0f} x {bh:.0f} x {width:.0f} mm, Rueckseite X={bx:g}, Unterkante Y={by:.1f}")

    # ---- values ---------------------------------------------------------
    def values(self) -> dict[str, str]:
        out = {}
        for key, w in self.inputs.items():
            if isinstance(w, QComboBox):
                out[key] = w.currentText().strip()
            elif hasattr(w, "ja"):
                out[key] = "ja" if w.ja.isChecked() else "nein"
            else:
                out[key] = w.text().strip()
        return out

    def set_values(self, vals: dict[str, str]):
        for key, v in vals.items():
            w = self.inputs.get(key)
            if w is None:
                continue
            w.blockSignals(True)
            if isinstance(w, QComboBox):
                w.setCurrentText(v)
            elif hasattr(w, "ja"):
                (w.ja if v == "ja" else w.nein).setChecked(True)
            else:
                w.setText(v)
            w.blockSignals(False)
        self.schedule()

    def schedule(self, *_):
        self._timer.start(200)

    def _layers_changed(self, *_):
        shown = {key: box.isChecked() for key, box in self.layer_boxes.items()}
        self.state.set(f"{self.model.key}_layers", shown)
        self.front.set_layers(shown); self.top.set_layers(shown)

    # ---- build ------------------------------------------------------------
    def _message(self, text: str, style: str):
        lab = QLabel(text); lab.setWordWrap(True); lab.setStyleSheet(style)
        self.messages.addWidget(lab)

    def rebuild(self) -> bool:
        while self.messages.count():
            item = self.messages.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        vals = self.values()
        self.state.set(self.model.key, vals)
        cat = field_catalogue(self.model.fields)
        bad = []
        for key, (label, unit, default, help_, kind) in cat.items():
            w = self.inputs[key]
            if kind in ("num", "int") and vals[key]:
                try:
                    float(vals[key].replace(",", "."))
                    w.setStyleSheet("")
                except ValueError:
                    bad.append(label); w.setStyleSheet("background:#ffd6d6;")
        try:
            gap = float(self.gap.text().replace(",", "."))
            if gap <= 0:
                raise ValueError
            if abs(gap - self.machine.tower_gap_mm) > 1e-9:
                self.machine.tower_gap_mm = gap; self.machine.tower_gap_measured = True
                self.machine.save(); self.log(f"Turmabstand {gap:g} mm gespeichert")
        except ValueError:
            bad.append("Turmabstand")
        fixed = self.fixed.currentIndex() + 1
        if fixed != self.machine.wire_fixed_tower:
            self.machine.wire_fixed_tower = fixed
            self.machine.save(); self.log(f"Draht fest an Turm {fixed} gespeichert")
        if bad:
            self._message("Keine Zahl: " + ", ".join(bad), ERR_STYLE)
            self.spec = self.path = None; self.gcode = ""
            return False
        try:
            spec = self.model.parse(self.model.to_text(vals))
            code, path = self.model.generate(spec, self.machine, self.airfoil_dir)
        except (WingError, ValueError, OSError) as e:
            self._message(f"Fehler: {e}", ERR_STYLE)
            self.spec = self.path = None; self.gcode = ""
            self.front.show_path(None, self.machine); self.top.show_path(None)
            return False
        self.spec, self.path, self.gcode = spec, path, code
        # chords derived from the area: show them, but do not let them be typed
        if hasattr(spec, "area"):
            derived = spec.area is not None
            for key, val in (("root_chord", spec.root_chord), ("tip_chord", spec.tip_chord)):
                w = self.inputs[key]
                w.setEnabled(not derived)
                if derived and w.text().strip() != f"{val:.1f}":
                    w.blockSignals(True); w.setText(f"{val:.1f}"); w.blockSignals(False)
        prog = gc.Program.parse(code)
        problems = self.machine.check_extents(path.extents()) if self.machine.has_travel() else []
        for n in path.notes:
            if n.startswith(("TURMABSTAND", "Tisch zu")) or "kreuzen" in n or "ragt" in n or "ausserhalb" in n:
                self._message(n, WARN_STYLE)
        for pr in problems:
            self._message(f"Verfahrweg: {pr}", ERR_STYLE)
        for e in prog.errors:
            self._message(f"G-Code: {e}", ERR_STYLE)
        ext = path.extents()
        lines = [n for n in path.notes if n.startswith(("Wurzel an", "Form:", "Mindestblock", "Tisch:", "Block bei", "V-Form", "Schnittzeit"))]
        t_lo, t_hi = path.table_range
        s_lo, s_hi, x_lo, _ = path.table_max
        self.table_hint.setText(
            f"Tisch: Oberkante bei Y = {path.table_y:.1f} (möglich {t_lo:.1f} bis "
            f"{t_hi:.1f}" + (")" if t_hi != float("inf") else ", oben ohne Verfahrweg unbekannt)")
            + f"; darf höchstens von s = {s_lo:.0f} bis {s_hi:.0f} reichen ({s_hi - s_lo:.0f} mm breit), "
            f"hinten frühestens {x_lo:g} mm vor dem Draht-Null beginnen, nach vorn beliebig. "
            "Weiter außen taucht der Draht unter die Tischhöhe.")
        bx, by, bl, bh, start, width = path.min_block
        self.minblock_hint.setText(
            f"Mindestens einzulegen: {bl:.0f} mm lang (X) × {bh:.0f} mm hoch (Y) × {width:.0f} mm breit "
            f"(Spannrichtung), Rückseite bei X = {bx:g}, Unterkante bei Y = {by:.1f}, ab Wurzelebene {start:g}. "
            "Der Knopf trägt diese Werte oben ein; leere Felder bedeuten ohnehin Mindestblock.")
        lines.append("Schlittenweg:  " + "   ".join(f"{a} {lo:.0f}..{hi:.0f}" for a, (lo, hi) in ext.items()))
        self.result.setText("\n".join(lines))
        if self.sent is not None:
            self.stale.setText("" if self.sent == code else "Programm ist VERALTET - erneut übergeben")
        self.front.show_path(path, self.machine); self.top.show_path(path)
        return not (problems or prog.errors)

    # ---- actions ------------------------------------------------------------
    def _name(self) -> str:
        return self.model.name(self.spec)

    def to_program(self):
        ok = self.rebuild()
        if not self.gcode:
            self.stale.setText("NICHT übergeben - Eingabefehler"); return
        self.sent = self.gcode
        self.gcode_ready.emit(self.gcode, self._name())
        self.stale.setText(("übergeben: " if ok else "übergeben MIT WARNUNGEN: ") + self._name())
        self.log(f"Flügel-G-Code übernommen: {self._name()}")

    def save_gcode(self):
        self.rebuild()
        if not self.gcode:
            return
        p, _ = QFileDialog.getSaveFileName(self, "G-Code speichern", self.state.get("last_dir", "gcode"), "G-Code (*.nc)")
        if p:
            Path(p).write_text(self.gcode); self.state.set("last_dir", str(Path(p).parent))
            self.sent = self.gcode
            self.gcode_ready.emit(self.gcode, Path(p).name)
            self.stale.setText(f"gespeichert und übergeben: {Path(p).name}")
            self.log(f"G-Code gespeichert: {p}")

    def load_spec(self):
        p, _ = QFileDialog.getOpenFileName(self, f"{self.model.title} laden", self.state.get("last_dir", "gcode"),
                                           self.model.file_filter)
        if p:
            self.set_values(self._values_from_file(Path(p).read_text())); self.state.set("last_dir", str(Path(p).parent))

    def _values_from_file(self, text: str) -> dict[str, str]:
        return self.model.values_from_file(text, self.machine, self.airfoil_dir)

    def save_spec(self):
        p, _ = QFileDialog.getSaveFileName(self, f"{self.model.title} speichern", self.state.get("last_dir", "gcode"),
                                           self.model.file_filter.split(";;")[0])
        if p:
            Path(p).write_text(self.model.to_text(self.values())); self.state.set("last_dir", str(Path(p).parent))
            self.log(f"Flügel gespeichert: {p}")


WingPage = DesignPage
