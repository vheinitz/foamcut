"""Nesting page: several saved parts, stacked in one block, one program."""
from __future__ import annotations

import copy
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QFileDialog, QLabel, QListWidgetItem, QWidget

from .. import gcode as gc
from ..machine import Machine
from ..nest import Batch, Item, generate
from ..wing import WingError
from .canvas import LAYERS, FrontView, TopView, ViewFrame
from .state import UiState
from .uiload import load_ui
from .wingpage import ERR_STYLE, LAYER_COLUMNS, WARN_STYLE, _ignore_width


class BatchPage(QWidget):
    gcode_ready = pyqtSignal(str, str)

    def __init__(self, machine: Machine, airfoil_dir: Path, state: UiState, log, parent=None):
        super().__init__(parent)
        self.machine, self.airfoil_dir, self.state, self.log = machine, airfoil_dir, state, log
        self.nest = None; self.gcode = ""; self.sent = None
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.timeout.connect(self.rebuild)
        saved = state.get("batch", {})

        load_ui("batchpage", self)
        self.list.itemChanged.connect(self.schedule)
        self.b_add.clicked.connect(self.add_files); self.b_remove.clicked.connect(self.remove)
        self.b_up.clicked.connect(lambda: self.move(-1)); self.b_down.clicked.connect(lambda: self.move(1))
        self.f = {key: getattr(self, f"f_{key}") for key in
                  ("block_x", "table_y", "root_gap", "gap", "block_len", "block_h", "block_w")}
        defaults = {"block_x": "20", "table_y": "20", "root_gap": "150", "gap": "8"}
        for key, w in self.f.items():
            w.setText(str(saved.get(key, defaults.get(key, "")))); w.textChanged.connect(self.schedule)
        for f in saved.get("items", []):
            self._add_item(f["file"], f.get("pair", False))

        # ---- right: drawing, messages, result -------------------------------------
        self.front = FrontView(); self.top = TopView()
        self.views.addWidget(ViewFrame(self.front)); self.views.addWidget(ViewFrame(self.top)); self.views.setSizes([460, 220])
        shown = state.get("wing_layers", {})
        self.layer_boxes = {}
        for i, (key, text) in enumerate(LAYERS):
            box = QCheckBox(text); box.setChecked(bool(shown.get(key, True))); box.toggled.connect(self._layers)
            self.layer_layout.addWidget(box, i // LAYER_COLUMNS, i % LAYER_COLUMNS); self.layer_boxes[key] = box
        self._layers()
        self.messages = self.messages_layout
        self.b_load.clicked.connect(self.load_batch); self.b_save.clicked.connect(self.save_batch)
        self.b_gcode.clicked.connect(self.save_gcode); self.b_prog.clicked.connect(self.to_program)
        self.split.setSizes([560, 820]); self.split.setStretchFactor(0, 2); self.split.setStretchFactor(1, 3)
        self.block_grid.setColumnStretch(2, 1)
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
                                                "Teile (*.wing *.shape *.contour *.slices);;alle (*)")
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
    def batch(self) -> Batch:
        def num(key, optional=False):
            t = self.f[key].text().strip().replace(",", ".")
            if optional and not t:
                return None
            return float(t)
        b = Batch(block_x=num("block_x"), table_y=num("table_y"), root_gap=num("root_gap"), gap=num("gap"),
                  block_len=num("block_len", True), block_h=num("block_h", True), block_w=num("block_w", True),
                  items=self.items())
        return b

    def _message(self, text, style):
        lab = QLabel(text); lab.setWordWrap(True); lab.setStyleSheet(style); _ignore_width(lab); self.messages.addWidget(lab)

    def rebuild(self) -> bool:
        while self.messages.count():
            w = self.messages.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.state.set("batch", {**{k: w.text() for k, w in self.f.items()},
                                 "items": [{"file": it.file, "pair": it.pair} for it in self.items()]})
        try:
            batch = self.batch()
        except ValueError:
            self._message("Keine Zahl in den Blockfeldern", ERR_STYLE); self.nest = None; self.gcode = ""; return False
        if not batch.items:
            self.result.setText("Teile laden (.wing / .shape / .contour / .slices), dann werden sie hier gestapelt."); self.nest = None; self.gcode = ""
            self.front.show_path(None, self.machine); self.top.show_path(None); return False
        try:
            code, nest = generate(batch, self.machine, self.airfoil_dir)
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
                b = self.batch()
            except ValueError:
                self.log("! Liste nicht gespeichert: keine Zahl in den Blockfeldern"); return
            Path(p).write_text(b.to_text()); self.log(f"Liste gespeichert: {p}")
