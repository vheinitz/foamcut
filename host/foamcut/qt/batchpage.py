"""Nesting page: several saved parts, stacked in one block, one program."""
from __future__ import annotations

import copy
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPushButton, QSplitter, QVBoxLayout, QWidget)

from .. import gcode as gc
from ..machine import Machine
from ..nest import Batch, Item, generate
from ..wing import WingError
from .canvas import LAYERS, FrontView, TopView
from .state import UiState
from .wingpage import ERR_STYLE, WARN_STYLE


class BatchPage(QWidget):
    gcode_ready = pyqtSignal(str, str)

    def __init__(self, machine: Machine, airfoil_dir: Path, state: UiState, log, parent=None):
        super().__init__(parent)
        self.machine, self.airfoil_dir, self.state, self.log = machine, airfoil_dir, state, log
        self.nest = None; self.gcode = ""; self.sent = None
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.timeout.connect(self.rebuild)
        saved = state.get("batch", {})

        # ---- left: list of parts + block -----------------------------------
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Teile (Schnittreihenfolge von oben nach unten; das letzte liegt auf dem Tisch):"))
        self.list = QListWidget(); lv.addWidget(self.list, 1)
        self.list.itemChanged.connect(self.schedule)
        row = QHBoxLayout()
        for text, fn in (("Teil laden…", self.add_files), ("Entfernen", self.remove), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1))):
            b = QPushButton(text); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); lv.addLayout(row)
        form = QFormLayout(); form.setVerticalSpacing(3)
        self.f = {}
        for key, label, default, help_ in (
                ("block_x", "Block Rückseite X [mm]", "20", "wo der Draht in den Block eintaucht"),
                ("table_y", "Tischoberkante Y [mm]", "20", "Blockunterkante"),
                ("root_gap", "Wurzelseite ab Turm [mm]", "150", "Abstand des Blocks vom Turm mit festem Draht"),
                ("gap", "Abstand zwischen Teilen [mm]", "8", "Schaum, der zwischen zwei gestapelten Teilen stehen bleibt"),
                ("block_len", "Block Länge X [mm]", "", "leer = Mindestblock; sonst wird geprüft, ob es passt"),
                ("block_h", "Block Höhe Y [mm]", "", "leer = Mindestblock"),
                ("block_w", "Block Breite (Spann) [mm]", "", "leer = längstes Teil + Rand"),
                ("feed", "Drahtvorschub [mm/min]", f"{machine.cut_feed:g}", "für alle Teile")):
            w = QLineEdit(str(saved.get(key, default))); w.setMaximumWidth(90); w.setAlignment(Qt.AlignmentFlag.AlignRight)
            w.textChanged.connect(self.schedule); self.f[key] = w
            r = QWidget(); rl = QHBoxLayout(r); rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(w); h = QLabel(help_); h.setStyleSheet("color:#666; font-size:9pt;"); rl.addWidget(h); rl.addStretch()
            form.addRow(label, r)
        lv.addLayout(form)
        for f in saved.get("items", []):
            self._add_item(f["file"], f.get("pair", False))

        # ---- right: drawing, messages, result -------------------------------------
        self.front = FrontView(); self.top = TopView()
        shown = state.get("wing_layers", {})
        bar = QHBoxLayout(); bar.addWidget(QLabel("Einblenden:")); self.layer_boxes = {}
        for key, text in LAYERS:
            box = QCheckBox(text); box.setChecked(bool(shown.get(key, True))); box.toggled.connect(self._layers)
            bar.addWidget(box); self.layer_boxes[key] = box
        bar.addStretch()
        self.messages = QVBoxLayout(); self.messages.setSpacing(3); msg = QWidget(); msg.setLayout(self.messages)
        self.result = QLabel(""); self.result.setStyleSheet("font-family:monospace; font-size:9pt;")
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(bar)
        views = QSplitter(Qt.Orientation.Vertical); views.addWidget(self.front); views.addWidget(self.top); views.setSizes([460, 220])
        rv.addWidget(views, 1); rv.addWidget(msg); rv.addWidget(self.result)
        self._layers()

        bottom = QHBoxLayout()
        b = QPushButton("Liste laden…"); b.clicked.connect(self.load_batch); bottom.addWidget(b)
        b = QPushButton("Liste speichern…"); b.clicked.connect(self.save_batch); bottom.addWidget(b)
        self.stale = QLabel(""); self.stale.setStyleSheet("color:#b00; font-weight:bold;")
        bottom.addSpacing(16); bottom.addWidget(self.stale); bottom.addStretch()
        b = QPushButton("G-Code speichern…"); b.clicked.connect(self.save_gcode); bottom.addWidget(b)
        b = QPushButton("→ Programm"); b.clicked.connect(self.to_program); bottom.addWidget(b)

        split = QSplitter(); split.addWidget(left); split.addWidget(right); split.setSizes([560, 820])
        outer = QVBoxLayout(self); outer.addWidget(split, 1); outer.addLayout(bottom)
        QTimer.singleShot(0, self.rebuild)

    # ---- list handling ---------------------------------------------------------
    def _add_item(self, file: str, pair: bool = False):
        it = QListWidgetItem(f"{Path(file).name}    [{file}]")
        it.setData(Qt.ItemDataRole.UserRole, file)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if pair else Qt.CheckState.Unchecked)
        it.setToolTip("Haken = Paar: zusätzlich das Spiegelbild (in Spannrichtung umgedreht) darüber")
        self.list.addItem(it)

    def items(self) -> list[Item]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            out.append(Item(it.data(Qt.ItemDataRole.UserRole), it.checkState() == Qt.CheckState.Checked))
        return out

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Teile laden", self.state.get("last_dir", "gcode"),
                                                "Teile (*.wing *.shape);;alle (*)")
        for f in files:
            self._add_item(f); self.state.set("last_dir", str(Path(f).parent))
        self.schedule()

    def remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self.schedule()

    def move(self, d: int):
        row = self.list.currentRow()
        if row < 0 or not 0 <= row + d < self.list.count():
            return
        it = self.list.takeItem(row); self.list.insertItem(row + d, it); self.list.setCurrentRow(row + d)
        self.schedule()

    def _layers(self, *_):
        shown = {k: b.isChecked() for k, b in self.layer_boxes.items()}
        self.front.set_layers(shown); self.top.set_layers(shown)

    def schedule(self, *_):
        self._timer.start(200)

    # ---- build ------------------------------------------------------------------
    def batch(self) -> tuple[Batch, float]:
        def num(key, optional=False):
            t = self.f[key].text().strip().replace(",", ".")
            if optional and not t:
                return None
            return float(t)
        b = Batch(block_x=num("block_x"), table_y=num("table_y"), root_gap=num("root_gap"), gap=num("gap"),
                  block_len=num("block_len", True), block_h=num("block_h", True), block_w=num("block_w", True),
                  items=self.items())
        return b, num("feed")

    def _message(self, text, style):
        lab = QLabel(text); lab.setWordWrap(True); lab.setStyleSheet(style); self.messages.addWidget(lab)

    def rebuild(self) -> bool:
        while self.messages.count():
            w = self.messages.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.state.set("batch", {**{k: w.text() for k, w in self.f.items()},
                                 "items": [{"file": it.file, "pair": it.pair} for it in self.items()]})
        try:
            batch, feed = self.batch()
        except ValueError:
            self._message("Keine Zahl in den Blockfeldern", ERR_STYLE); self.nest = None; self.gcode = ""; return False
        if not batch.items:
            self.result.setText("Teile laden (.wing / .shape), dann werden sie hier gestapelt."); self.nest = None; self.gcode = ""
            self.front.show_path(None, self.machine); self.top.show_path(None); return False
        try:
            code, nest = generate(batch, self.machine, self.airfoil_dir, feed)
        except (WingError, ValueError, OSError) as e:
            self._message(f"Fehler: {e}", ERR_STYLE); self.nest = None; self.gcode = ""
            self.front.show_path(None, self.machine); self.top.show_path(None); return False
        self.nest, self.gcode = nest, code
        prog = gc.Program.parse(code)
        problems = self.machine.check_extents(nest.extents()) if self.machine.has_travel() else []
        for n in nest.notes:
            if n.startswith(("Block zu", "Tisch zu")):
                self._message(n, WARN_STYLE)
        for pr in problems:
            self._message(f"Verfahrweg: {pr}", ERR_STYLE)
        for e in prog.errors:
            self._message(f"G-Code: {e}", ERR_STYLE)
        ext = nest.extents()
        lines = [n for n in nest.notes if not n.startswith(("Block zu", "Tisch zu"))]
        lines.append("Schlittenweg:  " + "   ".join(f"{a} {lo:.0f}..{hi:.0f}" for a, (lo, hi) in ext.items()))
        self.result.setText("\n".join(lines))
        if self.sent is not None:
            self.stale.setText("" if self.sent == code else "Programm ist VERALTET - erneut übergeben")
        p0 = copy.copy(nest.path)
        p0.block, p0.block_s, p0.table_max = nest.block, nest.block_s, nest.table_max
        self.front.show_path(p0, self.machine, extra=[pl.path for pl in nest.parts[1:]])
        self.top.show_path(p0)
        return not (problems or prog.errors)

    # ---- actions ------------------------------------------------------------------
    def _name(self) -> str:
        return f"nest_{len(self.nest.parts)}teile.nc"

    def to_program(self):
        ok = self.rebuild()
        if not self.gcode:
            self.stale.setText("NICHT übergeben - Eingabefehler"); return
        self.sent = self.gcode
        self.gcode_ready.emit(self.gcode, self._name())
        self.stale.setText(("übergeben: " if ok else "übergeben MIT WARNUNGEN: ") + self._name())
        self.log(f"Schachtel-G-Code übernommen: {self._name()}")

    def save_gcode(self):
        self.rebuild()
        if not self.gcode:
            return
        p, _ = QFileDialog.getSaveFileName(self, "G-Code speichern", self.state.get("last_dir", "gcode"), "G-Code (*.nc)")
        if p:
            Path(p).write_text(self.gcode); self.sent = self.gcode
            self.gcode_ready.emit(self.gcode, Path(p).name); self.stale.setText(f"gespeichert und übergeben: {Path(p).name}")

    def load_batch(self):
        p, _ = QFileDialog.getOpenFileName(self, "Liste laden", self.state.get("last_dir", "gcode"), "batch (*.batch);;alle (*)")
        if p:
            self.set_batch(Batch.parse(Path(p).read_text(), Path(p).parent)); self.state.set("last_dir", str(Path(p).parent))

    def set_batch(self, b: Batch):
        self.list.clear()
        for it in b.items:
            self._add_item(it.file, it.pair)
        for key in ("block_x", "table_y", "root_gap", "gap", "block_len", "block_h", "block_w"):
            v = getattr(b, key)
            self.f[key].setText("" if v is None else f"{v:g}")
        self.schedule()

    def save_batch(self):
        p, _ = QFileDialog.getSaveFileName(self, "Liste speichern", self.state.get("last_dir", "gcode"), "batch (*.batch)")
        if p:
            try:
                b, _ = self.batch()
            except ValueError:
                self.log("! Liste nicht gespeichert: keine Zahl in den Blockfeldern"); return
            Path(p).write_text(b.to_text()); self.log(f"Liste gespeichert: {p}")
