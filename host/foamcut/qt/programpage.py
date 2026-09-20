"""Program page: load / translate, simulate (turtle), run with pause and stop."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                             QPushButton, QSlider, QSplitter, QVBoxLayout, QWidget)

from .. import gcode as gc
from ..machine import Machine
from ..sim import segments, total_seconds
from .canvas import C, SimView
from .state import UiState


class ProgramPage(QWidget):
    start_requested = pyqtSignal(list)      # translated lines
    pause_requested = pyqtSignal(bool)      # True = pause, False = resume
    stop_requested = pyqtSignal()

    def __init__(self, machine: Machine, state: UiState, wire_power, log, parent=None):
        super().__init__(parent)
        self.machine, self.state, self.wire_power, self.log = machine, state, wire_power, log
        self.raw = ""; self.name = ""; self.lines: list[str] = []; self.problems: list[str] = []
        self.segs = []; self.i = 0; self.running = False; self.paused = False
        self.timer = QTimer(self); self.timer.timeout.connect(self._tick)

        v = QVBoxLayout(self)
        row = QHBoxLayout()
        b = QPushButton("Datei…"); b.clicked.connect(self.load_file); row.addWidget(b)
        row.addWidget(QLabel("Format"))
        self.fmt = QComboBox(); self.fmt.addItems(["auto", *gc.AXIS_PRESETS]); self.fmt.currentTextChanged.connect(lambda _: self.prepare())
        row.addWidget(self.fmt)
        self.title = QLabel("kein Programm geladen"); self.title.setStyleSheet("font-size:13pt; font-weight:bold;")
        row.addWidget(self.title, 1)
        self.b_start = QPushButton("Start"); self.b_start.setEnabled(False); self.b_start.clicked.connect(self.start)
        self.b_pause = QPushButton("Pause"); self.b_pause.setEnabled(False); self.b_pause.clicked.connect(self.pause)
        self.b_stop = QPushButton("STOP"); self.b_stop.setEnabled(False); self.b_stop.clicked.connect(self.stop_requested)
        self.b_stop.setStyleSheet("font-weight:bold; color:#b00;")
        for b in (self.b_start, self.b_pause, self.b_stop):
            row.addWidget(b)
        v.addLayout(row)
        self.progress = QProgressBar(); v.addWidget(self.progress)
        self.line_lbl = QLabel(""); self.line_lbl.setStyleSheet("font-family:monospace;"); v.addWidget(self.line_lbl)

        # ---- simulation ------------------------------------------------
        self.v1 = SimView("Turm 1   X →   Y ↑", C["root"])
        self.v2 = SimView("Turm 2   U →   V ↑", C["tip"])
        split = QSplitter(); split.addWidget(self.v1); split.addWidget(self.v2)
        v.addWidget(split, 1)
        sim = QHBoxLayout()
        sim.addWidget(QLabel("Simulation:"))
        self.b_run = QPushButton("Start"); self.b_run.clicked.connect(self.sim_run); sim.addWidget(self.b_run)
        b = QPushButton("Schritt"); b.clicked.connect(self.sim_step); sim.addWidget(b)
        b = QPushButton("Zurück"); b.clicked.connect(self.sim_reset); sim.addWidget(b)
        b = QPushButton("Alles sofort"); b.clicked.connect(self.sim_finish); sim.addWidget(b)
        sim.addSpacing(12); sim.addWidget(QLabel("Tempo"))
        self.speed = QSlider(Qt.Orientation.Horizontal); self.speed.setRange(1, 100); self.speed.setValue(10); self.speed.setMaximumWidth(160)
        self.speed_lbl = QLabel("10x"); self.speed.valueChanged.connect(lambda val: self.speed_lbl.setText(f"{val}x"))
        sim.addWidget(self.speed); sim.addWidget(self.speed_lbl)
        self.sim_info = QLabel(""); self.sim_info.setStyleSheet("font-family:monospace;")
        sim.addSpacing(12); sim.addWidget(self.sim_info, 1)
        v.addLayout(sim)
        self.notes = QLabel(""); self.notes.setWordWrap(True); self.notes.setStyleSheet("font-family:monospace; font-size:9pt;")
        v.addWidget(self.notes)

        last = state.get("last_program")
        if last and Path(last).exists():
            self.set_program(Path(last).read_text(errors="replace"), Path(last).name, path=last)

    # ---- loading --------------------------------------------------------
    def load_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "G-Code laden", self.state.get("last_dir", "gcode"),
                                           "G-Code (*.nc *.gcode *.ngc *.txt);;alle (*)")
        if p:
            self.state.set("last_dir", str(Path(p).parent))
            self.set_program(Path(p).read_text(errors="replace"), Path(p).name, path=p)

    def set_program(self, raw: str, name: str, path: str | None = None, start_pos: dict | None = None):
        self.raw, self.name = raw, name
        self.start_pos = start_pos          # relative programs: where they begin
        if path:
            self.state.set("last_program", path)
        self.log(f"--- Programm: {name}")
        self.prepare()

    def prepare(self) -> bool:
        if not self.raw:
            return False
        text, notes = gc.translate(self.raw, preset=self.fmt.currentText(),
                                   wire_power=self.wire_power() or None, default_feed=self.machine.cut_feed)
        prog = gc.Program.parse(text, start=getattr(self, "start_pos", None))
        problems = self.machine.check_extents(prog.extents()) if self.machine.has_travel() else []
        self.lines = text.splitlines()
        self.problems = list(prog.errors) + problems
        self.title.setText(f"{self.name}   ({len(prog.moves)} Bewegungen)")
        out = [f"umgesetzt: {n}" for n in notes] + prog.report().splitlines() + [f"VERFAHRWEG: {p}" for p in problems]
        if not self.machine.has_travel():
            out.append("(Verfahrweg nicht vermessen - keine Bereichsprüfung)")
        self.notes.setText("\n".join(out))
        self.b_start.setEnabled(True)
        self.progress.setRange(0, max(1, len(self.lines))); self.progress.setValue(0)
        # simulation
        self.segs = segments(prog, rapid_feed=max(self.machine.max_rate.values()))
        t = self.machine.travel_mm if self.machine.has_travel() else None
        self.v1.load(self.segs, 1, (t["X"], t["Y"]) if t else None)
        self.v2.load(self.segs, 2, (t["U"], t["V"]) if t else None)
        self.sim_reset()
        return not self.problems

    # ---- running --------------------------------------------------------
    def start(self):
        if not self.raw:
            return
        self.prepare()
        if self.problems and QMessageBox.question(self, "Probleme", "\n".join(self.problems[:8]) + "\n\nTrotzdem starten?") != QMessageBox.StandardButton.Yes:
            return
        if QMessageBox.question(self, "Start", f"{self.name}\n\nDieses Programm abspielen?\nReferenz gesetzt? Drahtleistung eingestellt?") != QMessageBox.StandardButton.Yes:
            return
        self.running = True; self.paused = False
        self.b_start.setEnabled(False); self.b_pause.setEnabled(True); self.b_pause.setText("Pause"); self.b_stop.setEnabled(True)
        self.v1.clear_live(); self.v2.clear_live(); self.v1.set_progress(0); self.v2.set_progress(0)
        self.start_requested.emit(list(self.lines))

    def pause(self):
        self.paused = not self.paused
        self.b_pause.setText("Weiter" if self.paused else "Pause")
        self.pause_requested.emit(self.paused)

    def on_progress(self, i, n, line):
        self.progress.setRange(0, n); self.progress.setValue(i)
        self.line_lbl.setText(f"{i}/{n}  {line}")
        # segments of the lines grbl has accepted so far: the planned path
        # fills in ahead of the real position (grbl buffers ~16 moves)
        upto = sum(1 for s in self.segs if s.line_no <= i)
        self.v1.set_progress(upto); self.v2.set_progress(upto)

    def on_status(self, wpos: dict):
        """Live: the real carriage positions on both views while a program runs."""
        if not self.running:
            return
        self.v1.set_live((wpos["X"], wpos["Y"])); self.v2.set_live((wpos["U"], wpos["V"]))

    def on_finished(self, ok: bool):
        self.running = False; self.paused = False
        self.v1.set_live(None); self.v2.set_live(None)        # the trail stays until the next start
        self.b_start.setEnabled(bool(self.lines)); self.b_pause.setEnabled(False); self.b_pause.setText("Pause"); self.b_stop.setEnabled(False)
        self.log("Programm fertig." if ok else "Programm abgebrochen.")

    # ---- simulation -----------------------------------------------------
    def _info(self):
        if not self.segs:
            self.sim_info.setText(""); return
        i = self.i; total = total_seconds(self.segs); done = sum(s.seconds for s in self.segs[:i])
        s = self.segs[min(i, len(self.segs) - 1)]
        pos = s.t1_end if i else s.t1_start; pos2 = s.t2_end if i else s.t2_start
        kind = "Ende" if i >= len(self.segs) else ("Eilgang" if s.rapid else "Schnitt")
        self.sim_info.setText(f"Segment {i}/{len(self.segs)}  Zeile {s.line_no}  {kind}  "
                              f"X{pos[0]:.2f} Y{pos[1]:.2f}  U{pos2[0]:.2f} V{pos2[1]:.2f}  {done / 60:.1f}/{total / 60:.1f} min")

    def sim_step(self):
        if self.i >= len(self.segs):
            return 0.0
        secs = self.segs[self.i].seconds
        self.i += 1
        self.v1.set_progress(self.i); self.v2.set_progress(self.i); self._info()
        return secs

    def _tick(self):
        secs = self.sim_step()
        if self.i >= len(self.segs):
            self.timer.stop(); self.b_run.setText("Start"); return
        self.timer.start(max(15, int(secs * 1000 / max(self.speed.value(), 1))))

    def sim_run(self):
        if self.timer.isActive():
            self.timer.stop(); self.b_run.setText("Start"); return
        if self.i >= len(self.segs):
            self.sim_reset()
        self.b_run.setText("Pause"); self._tick()

    def sim_reset(self):
        self.timer.stop(); self.b_run.setText("Start"); self.i = 0
        self.v1.set_progress(0); self.v2.set_progress(0); self._info()

    def sim_finish(self):
        self.timer.stop(); self.b_run.setText("Start"); self.i = len(self.segs)
        self.v1.set_progress(self.i); self.v2.set_progress(self.i); self._info()
