"""Design page (wings, free shapes): steps on the left, live drawing on the
right, warnings inline. Which fields, parser and generator it drives comes
from a wing.Model."""
from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QWidget)

from .. import gcode as gc
from ..machine import Machine
from ..wing import WING_MODEL, Model, WingError, field_catalogue
from .canvas import LAYERS, FrontView, MeshView, ObjectView, TopView, ViewFrame
from .state import UiState
from .uiload import load_ui

LAYER_COLUMNS = 4          # the "Einblenden" checkboxes wrap into this many columns

WARN_STYLE = "background:#fff4d6; border:1px solid #e0c070; padding:4px 8px; border-radius:4px;"
ERR_STYLE = "background:#ffd9d9; border:1px solid #e08080; padding:4px 8px; border-radius:4px;"


def _ignore_width(label):
    """A wrapped label must not widen the window: its text wraps to whatever
    width the layout gives it (heightForWidth still works with Ignored)."""
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
OK_STYLE = "background:#e4f5e4; border:1px solid #8fd19e; padding:4px 8px; border-radius:4px;"


class DesignPage(QWidget):
    gcode_ready = pyqtSignal(str, str)          # (gcode text, name)
    queue_ready = pyqtSignal(list)              # [(name, gcode)] to run one after another (boards)

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

        load_ui("designpage", self)      # nav, stack, layer_layout, views, messages_layout, result, bottom bar
        # ---- left: step list + stacked forms (one page per FIELDS section) --
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
                elif kind.startswith("file:"):
                    w = QLineEdit(str(value)); w.setMinimumWidth(100)
                    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                    w.textChanged.connect(self.schedule)
                    w.browse = QPushButton("…"); w.browse.setMaximumWidth(28)
                    w.browse.clicked.connect(lambda _, w=w, ext=kind.split(":", 1)[1], label=label:
                                             self._pick_file(w, ext, label))
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
                if hasattr(w, "browse"):
                    rl.addWidget(w.browse)
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
        self.views.addWidget(ViewFrame(self.front)); self.views.addWidget(ViewFrame(self.top)); self.views.setSizes([460, 220])
        # "Objekt" tab: the source drawing / body of models that have one
        self.object_view = None
        if self.model.preview_kind == "loops":
            self.object_view = ObjectView(); self.object_layout.addWidget(ViewFrame(self.object_view))
        elif self.model.preview_kind == "mesh":
            self.object_view = MeshView(); self.object_layout.addWidget(self.object_view)
        else:
            self.view_tabs.removeTab(self.view_tabs.indexOf(self.tab_object))
        shown = state.get(f"{model.key}_layers", {})
        self.layer_boxes: dict[str, QCheckBox] = {}
        for i, (key, text) in enumerate(LAYERS):
            box = QCheckBox(text); box.setChecked(bool(shown.get(key, True)))
            box.toggled.connect(self._layers_changed)
            self.layer_layout.addWidget(box, i // LAYER_COLUMNS, i % LAYER_COLUMNS); self.layer_boxes[key] = box
        self._layers_changed()
        self.messages = self.messages_layout

        # ---- bottom bar ------------------------------------------------
        self.b_load.clicked.connect(self.load_spec); self.b_save.clicked.connect(self.save_spec)
        self.b_gcode.clicked.connect(self.save_gcode); self.b_prog.clicked.connect(self.to_program)
        self.split.setSizes([620, 760])
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
    def _pick_file(self, w, ext: str, label: str):
        p, _ = QFileDialog.getOpenFileName(self, label, self.state.get("last_dir", "gcode"),
                                           f"{ext.upper()} (*.{ext});;alle (*)")
        if p:
            w.setText(p); self.state.set("last_dir", str(Path(p).parent))

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
        lab = QLabel(text); lab.setWordWrap(True); lab.setStyleSheet(style); _ignore_width(lab)
        self.messages.addWidget(lab)

    def rebuild(self) -> bool:
        while self.messages.count():
            item = self.messages.takeAt(0)
            if item.widget():
                item.widget().hide(); item.widget().deleteLater()
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
        if self.object_view is not None:
            try:
                self.object_view.set_object(self.model.preview(spec))
            except (WingError, ValueError, OSError) as e:
                self.log(f"! Vorschau: {e}")
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
            if (n.startswith(("TURMABSTAND", "Tisch zu", "Text nicht")) or "kreuzen" in n or "ragt" in n
                    or "ausserhalb" in n):
                self._message(n, WARN_STYLE)
        for pr in problems:
            self._message(f"Verfahrweg: {pr}", ERR_STYLE)
        for e in prog.errors:
            self._message(f"G-Code: {e}", ERR_STYLE)
        ext = path.extents()
        lines = [n for n in path.notes if n.startswith(("Wurzel an", "Form:", "Kontur:", "Scheibe", "Platte", "Holmnut",
                                                        "Mindestblock", "Tisch:", "Block bei", "V-Form", "Schnittzeit"))
                 or " Teil(e)" in n]
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
        programs = list(getattr(self.path, "programs", []) or [])
        if len(programs) > 1:
            self.gcode_ready.emit(programs[0][1], programs[0][0])
            self.queue_ready.emit(programs[1:])
            self.log(f"{len(programs)} Programme (eine Platte je Programm): das naechste nach dem Plattenwechsel laden")
        else:
            self.gcode_ready.emit(self.gcode, self._name())
        self.stale.setText(("übergeben: " if ok else "übergeben MIT WARNUNGEN: ") + self._name())
        self.log(f"Flügel-G-Code übernommen: {self._name()}")

    def save_gcode(self):
        self.rebuild()
        if not self.gcode:
            return
        p, _ = QFileDialog.getSaveFileName(self, "G-Code speichern", self.state.get("last_dir", "gcode"), "G-Code (*.nc)")
        if p:
            programs = list(getattr(self.path, "programs", []) or [])
            if len(programs) > 1:                       # one file per board: name_platte1.nc, _platte2.nc, ...
                for k, (_, code) in enumerate(programs, start=1):
                    Path(p).with_name(f"{Path(p).stem}_platte{k}.nc").write_text(code)
                self.log(f"{len(programs)} Dateien gespeichert: {Path(p).stem}_platte1..{len(programs)}.nc")
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
