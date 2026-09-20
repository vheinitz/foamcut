"""Main window: step list on the left, pages on the right, worker pump, log."""
from __future__ import annotations

import queue
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QListWidget, QMainWindow, QPlainTextEdit,
                             QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from .. import AXES
from ..jog import JogModel
from ..machine import DEFAULT_PATH, Machine, standard_settings
from ..worker import GrblWorker
from .homingdialog import HomingDialog
from .machinepage import MachinePage
from .programpage import ProgramPage
from .state import UiState
from .wingpage import DesignPage
from ..shape import SHAPE_MODEL


class MainWindow(QMainWindow):
    def __init__(self, port: str = "auto", baud: int = 115200, machine_path: Path = DEFAULT_PATH,
                 autoconnect: bool = True, state: UiState | None = None):
        super().__init__()
        self.setWindowTitle("foamcut")
        self.machine_path = machine_path
        self.machine = Machine.load_or_none(machine_path) or Machine()
        self.state = state or UiState()
        self.model = JogModel(self.machine, feed_h=self.machine.jog_feed or 1e9, feed_v=1e9)
        self.worker: GrblWorker | None = None
        self.baud = baud
        self.mpos = {a: 0.0 for a in AXES}; self.wco = {a: 0.0 for a in AXES}
        self.streaming = False

        self.log_box = QPlainTextEdit(); self.log_box.setReadOnly(True); self.log_box.setMaximumBlockCount(2000)
        self.log_box.setStyleSheet("font-family:monospace; font-size:9pt;")

        self.machine_page = MachinePage(self.machine, self.model, self.log)
        self.machine_page.port.setText(port)
        self.wing_page = DesignPage(self.machine, Path("airfoil"), self.state, self.log)
        self.shape_page = DesignPage(self.machine, Path("airfoil"), self.state, self.log, model=SHAPE_MODEL)
        self.program_page = ProgramPage(self.machine, self.state, lambda: self.machine_page.power.value(), self.log)

        self.nav = QListWidget(); self.nav.setFixedWidth(190)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setStyleSheet("QListWidget{font-size:12pt; background:#1c2540; color:#cfd8ea; padding:6px;}"
                               "QListWidget::item{padding:10px 8px;} QListWidget::item:selected{background:#2f4370; color:white;}")
        self.stack = QStackedWidget()
        for title, page in (("Maschine", self.machine_page), ("Flügel", self.wing_page), ("Formen", self.shape_page),
                            ("Programm & Sim", self.program_page)):
            self.nav.addItem(title); self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(self.state.get("page", 0))
        self.nav.currentRowChanged.connect(lambda i: self.state.set("page", i))

        central = QWidget(); h = QHBoxLayout(central); h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.nav)
        right = QSplitter(); right.setOrientation(right.orientation().Vertical)
        right.addWidget(self.stack); right.addWidget(self.log_box); right.setSizes([700, 130])
        h.addWidget(right, 1)
        self.setCentralWidget(central)
        self.resize(*self.state.get("size", (1400, 880)))

        # ---- wiring --------------------------------------------------------
        self.machine_page.send_line.connect(self.send_line)
        self.machine_page.set_reference.connect(self.set_reference)
        self.machine_page.cut_requested.connect(self.straight_cut)
        self.machine_page.send_raw.connect(self.send_raw)
        self.machine_page.connect_toggle.connect(self.toggle_connection)
        self.machine_page.home_requested.connect(lambda: self.worker and self.worker.submit("home"))
        self.machine_page.homing_dialog.connect(self.open_homing)
        for page in (self.wing_page, self.shape_page):
            page.gcode_ready.connect(self.program_page.set_program)
            page.gcode_ready.connect(lambda *_: self.nav.setCurrentRow(3))
        self.program_page.start_requested.connect(self.start_program)
        self.program_page.pause_requested.connect(lambda p: self.send_raw(b"!" if p else b"~"))
        self.program_page.stop_requested.connect(self.stop_program)

        self.pump = QTimer(self); self.pump.timeout.connect(self._pump); self.pump.start(100)
        if autoconnect:
            QTimer.singleShot(200, self.toggle_connection)

    # ---- helpers -------------------------------------------------------------
    def log(self, text: str):
        self.log_box.appendPlainText(text)

    def wpos(self) -> dict:
        return {a: self.mpos[a] - self.wco[a] for a in AXES}

    def send_line(self, line: str):
        if self.worker:
            self.worker.submit("line", line)
        self.log(f"> {line}")

    def straight_cut(self, length: float, angle: float, feed: float, back: bool, du: float = 0.0, dv: float = 0.0):
        """Freischnitt: a straight relative cut from the current position, run
        through the program page so pause/stop/progress work as usual."""
        from ..jog import straight_cut
        code = straight_cut(length, angle, feed, warmup=3.0, back=back, skew=(du, dv))
        name = f"freischnitt_{length:g}mm_{angle:g}deg" + (f"_u{du:g}v{dv:g}" if (du or dv) else "") + ".nc"
        self.program_page.set_program(code, name, start_pos=self.wpos())
        self.nav.setCurrentRow(3)
        if self.program_page.prepare():
            self.program_page.start()
        else:
            self.log("! Freischnitt nicht gestartet - siehe Programmseite")

    def set_reference(self):
        """Work zero = where the carriages stand now. With switches this is
        stored as the offset from the homed position, so every later $H lands
        the same work zero; without switches it is grbl's G10 L20."""
        h = self.machine.homing
        if not h.enabled:
            self.send_line(self.model.set_reference()); return
        if not h.home_mpos:
            self.log("! erst Referenzfahrt ($H), dann Nullpunkt setzen"); return
        for a in AXES:
            h.offset_mm[a] = round(self.mpos[a] - h.home_mpos[a], 3)
        self.machine.save(self.machine_path)
        origin = h.work_origin(h.home_mpos)
        self.send_line("G10 L2 P1 " + " ".join(f"{a}{origin[a]:.3f}" for a in AXES)); self.send_line("G54")
        if self.worker:
            self.worker.submit("offset")
        self.log("Arbeitsnull = hier. Versatz ab Schalter gespeichert: "
                 + "  ".join(f"{a}{h.offset_mm[a]:+.3f}" for a in AXES))

    def send_raw(self, data: bytes):
        if self.worker:
            self.worker.submit("raw", data)
        names = {b"\x85": "STOP (Jog-Abbruch)", b"\x18": "Soft-Reset", b"!": "Pause", b"~": "weiter"}
        self.log(f"> {names.get(data, repr(data))}")

    def toggle_connection(self):
        if self.worker:
            self.worker.stop(); self.worker = None
            self.machine_page.b_conn.setText("Verbinden"); self.machine_page.state.setText("getrennt"); return
        self.worker = GrblWorker(self.machine_page.port.text().strip() or "auto", self.baud,
                                 settings=standard_settings(self.machine), homing=self.machine.homing)
        self.worker.start()
        self.machine_page.b_conn.setText("Trennen"); self.machine_page.state.setText("verbinde…")

    def start_program(self, lines: list[str]):
        if not self.worker:
            self.log("! nicht verbunden"); self.program_page.on_finished(False); return
        self.streaming = True
        self.worker.submit("stream", lines); self.log(f"> Start {self.program_page.name}")

    def stop_program(self):
        if self.worker:
            self.worker.abort_stream()
        self.log("> STOP Programm (Feed-Hold + Reset, Draht aus)")

    def open_homing(self):
        def saved():
            if self.worker:
                self.worker.homing = self.machine.homing
                self.worker.settings = standard_settings(self.machine)
                self.worker.submit("sync")
            self.machine_page.b_home.setEnabled(self.machine.homing.enabled)
        HomingDialog(self.machine, lambda: self.worker, self.log, saved, self).show()

    # ---- worker events -----------------------------------------------------
    def _pump(self):
        if not self.worker:
            return
        while True:
            try:
                kind, payload = self.worker.events.get_nowait()
            except queue.Empty:
                return
            if kind == "banner":
                for l in payload:
                    if l:
                        self.log(f"< {l}")
            elif kind == "status":
                self.mpos.update(payload.get("mpos", {}))
                self.model.wpos = self.wpos()
                self.machine_page.show_status(payload, self.model.wpos)
                self.program_page.on_status(self.model.wpos)
            elif kind == "offset":
                self.wco.update(payload)
            elif kind in ("reply", ):
                for l in payload:
                    self.log(f"< {l}")
            elif kind == "sent":
                self.log(f"> {payload}")
            elif kind == "error":
                self.log(f"! {payload}")
            elif kind == "progress":
                self.program_page.on_progress(*payload)
            elif kind == "stream_done":
                self.streaming = False
                self.program_page.on_finished(payload)
                if payload:
                    self.worker.submit("line", "M5")
            elif kind == "needs_homing":
                self.machine_page.unknown_position()
                if self.machine.homing.auto:
                    self.log("Position unbekannt - Referenzfahrt startet automatisch")
                    self.worker.submit("home")
                else:
                    self.log("! Position unbekannt - Referenzfahrt ($H) nötig, bis dahin bleibt grbl im Alarm")
            elif kind == "limit":
                self.log(f"!!! ENDSCHALTER {payload} während der Fahrt - Stopp, Position unbekannt. "
                         "Bei 0 darf kein Schalter ausgelöst sein: Referenzfahrt und Nullpunkt prüfen.")
                self.machine_page.unknown_position()
                if self.streaming:
                    self.streaming = False; self.program_page.on_finished(False)
            elif kind == "homed":
                self.log("Referenzfahrt fertig. Maschinenposition am Schalter: " + "  ".join(f"{a}{v:.3f}" for a, v in payload.items()))
                self.log("Arbeitsnull = Schalter + Versatz gesetzt (G54)."); self.machine.save(self.machine_path)
            elif kind == "reset":
                self.log("! Board wurde zurückgesetzt - Position unbekannt, " + ("Referenzfahrt nötig" if self.machine.homing.enabled else "Referenz neu setzen"))
                self.machine_page.unknown_position()
                if self.streaming:
                    self.streaming = False; self.program_page.on_finished(False)
            elif kind == "closed":
                self.worker = None
                self.machine_page.b_conn.setText("Verbinden"); self.machine_page.state.setText("getrennt")
                return

    def closeEvent(self, ev):
        if self.worker:
            self.worker.submit("line", "M5"); self.worker.stop()
        self.machine.jog_feed = self.model.feed_h
        self.machine.wire_power = self.machine_page.power.value()
        self.machine.save(self.machine_path)
        self.state.set("size", (self.width(), self.height()))
        super().closeEvent(ev)


def run(port: str = "auto", baud: int = 115200, machine_path: Path = DEFAULT_PATH) -> int:
    app = QApplication.instance() or QApplication([])
    win = MainWindow(port, baud, machine_path)
    win.show()
    return app.exec()
