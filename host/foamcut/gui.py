"""foamcut gui - mouse driven jog pad for the XYUV cutter.

Two towers side by side, each with its own arrow pad. Step size 1 / 5 / 25 /
100 mm, separate feeds for the horizontal (X, U) and vertical (Y, V) axes,
reference and travel buttons, hot wire control.

The serial link lives in a worker thread so the window never blocks on the
machine. All grbl logic sits in JogModel / GrblWorker and is unit tested; the
Tk part only wires buttons to those.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import AXES
from .grbl import Grbl, GrblAlarm, GrblError, parse_status
from .link import LinkError, SerialLink

try:
    from serial import SerialException as _SerialException
except ImportError:                                   # pragma: no cover
    class _SerialException(Exception):
        pass

_LINK_ERRORS = (LinkError, _SerialException, OSError)
from . import gcode as gc
from . import homing as hm
from .machine import DEFAULT_PATH, Homing, Machine, standard_settings



from .jog import HORIZONTAL, STEP_SIZES, VERTICAL, JogModel  # noqa: E402,F401
from .worker import GrblWorker  # noqa: E402  (shared with the Qt GUI)


# ------------------------------------------------------------------ tk ------
def run_gui(port: str = "auto", baud: int = 115200,
            machine_path: Path = DEFAULT_PATH) -> int:
    root = build_gui(port, baud, machine_path)
    root.mainloop()
    return 0


def build_gui(port: str = "auto", baud: int = 115200,
              machine_path: Path = DEFAULT_PATH, autoconnect: bool = True):
    """Build the main window and return the Tk root (no mainloop).

    Split from run_gui so a test can construct every widget and callback
    without a display session running the event loop forever.
    """
    import tkinter as tk
    from tkinter import ttk

    machine = Machine.load_or_none(machine_path) or Machine()
    model = JogModel(machine, feed_h=machine.jog_feed or 1e9, feed_v=1e9)   # both clamped to max
    worker: GrblWorker | None = None
    mpos = {a: 0.0 for a in AXES}
    wco = {a: 0.0 for a in AXES}

    root = tk.Tk()
    root.title("foamcut jog")
    root.minsize(720, 480)
    big = ("TkDefaultFont", 14)
    mono = ("TkFixedFont", 13)
    style = ttk.Style(root)
    style.configure("Jog.TButton", font=("TkDefaultFont", 16, "bold"), padding=8)
    style.configure("Act.TButton", padding=6)

    # -- top: connection + state ------------------------------------------
    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    port_var = tk.StringVar(value=port)
    ttk.Label(top, text="Port").pack(side="left")
    ttk.Entry(top, textvariable=port_var, width=14).pack(side="left", padx=4)
    state_var = tk.StringVar(value="nicht verbunden")
    ttk.Label(top, textvariable=state_var, font=big, width=12).pack(side="right")
    pins_var = tk.StringVar(value="")
    ttk.Label(top, textvariable=pins_var, foreground="#b00", font=big).pack(side="right", padx=12)
    conn_btn = ttk.Button(top, text="Verbinden", style="Act.TButton")
    conn_btn.pack(side="left", padx=4)

    # -- position --------------------------------------------------------
    posf = ttk.LabelFrame(root, text="Position (Arbeitskoordinaten, 0 = Referenzecke)", padding=8)
    posf.pack(fill="x", padx=8)
    pos_vars = {a: tk.StringVar(value="—") for a in AXES}
    for i, a in enumerate(AXES):
        ttk.Label(posf, text=a, font=big).grid(row=0, column=2 * i, padx=(12, 2))
        ttk.Label(posf, textvariable=pos_vars[a], font=mono, width=9, anchor="e").grid(row=0, column=2 * i + 1)

    # -- step + feeds -----------------------------------------------------
    ctl = ttk.Frame(root, padding=8)
    ctl.pack(fill="x")
    ttk.Label(ctl, text="Schritt").pack(side="left")
    step_var = tk.DoubleVar(value=model.step)
    for s in STEP_SIZES:
        ttk.Radiobutton(ctl, text=f"{s:g} mm", value=s, variable=step_var,
                        command=lambda: setattr(model, "step", step_var.get())).pack(side="left", padx=4)

    def feed_box(label, attr, maximum):
        ttk.Label(ctl, text=label).pack(side="left", padx=(16, 2))
        var = tk.DoubleVar(value=getattr(model, attr))
        sb = ttk.Spinbox(ctl, from_=10, to=maximum, increment=10, width=6, textvariable=var,
                         command=lambda: setattr(model, attr, min(var.get(), maximum)))
        sb.pack(side="left")
        sb.bind("<Return>", lambda e: setattr(model, attr, min(var.get(), maximum)))
        ttk.Label(ctl, text=f"mm/min (max {maximum:g})").pack(side="left")
        return var

    feed_box("waagerecht X/U", "feed_h", min(machine.max_rate[a] for a in HORIZONTAL))
    feed_box("senkrecht Y/V", "feed_v", min(machine.max_rate[a] for a in VERTICAL))

    # -- jog pads ---------------------------------------------------------
    pads = ttk.Frame(root, padding=8)
    pads.pack(fill="both", expand=True)

    def send(line: str):
        if worker:
            worker.submit("line", line)
        log(f"> {line}")

    def jog(moves):
        send(model.jog(moves))

    def pad(parent, title, h, v):
        f = ttk.LabelFrame(parent, text=title, padding=8)
        ttk.Button(f, text=f"▲ {v}+", style="Jog.TButton", command=lambda: jog({v: +1})).grid(row=0, column=1, pady=2)
        ttk.Button(f, text=f"◀ {h}−", style="Jog.TButton", command=lambda: jog({h: -1})).grid(row=1, column=0, padx=2)
        ttk.Label(f, text="hinten ◀ ▶ vorne", font=("TkDefaultFont", 9)).grid(row=1, column=1)
        ttk.Button(f, text=f"{h}+ ▶", style="Jog.TButton", command=lambda: jog({h: +1})).grid(row=1, column=2, padx=2)
        ttk.Button(f, text=f"▼ {v}−", style="Jog.TButton", command=lambda: jog({v: -1})).grid(row=2, column=1, pady=2)
        return f

    pad(pads, "Turm 1  (X / Y)", "X", "Y").grid(row=0, column=0, padx=8, sticky="n")
    both = ttk.LabelFrame(pads, text="beide Türme", padding=8)
    ttk.Button(both, text="▲ Y+V+", style="Jog.TButton", command=lambda: jog({"Y": +1, "V": +1})).grid(row=0, column=1, pady=2)
    ttk.Button(both, text="◀ X−U−", style="Jog.TButton", command=lambda: jog({"X": -1, "U": -1})).grid(row=1, column=0, padx=2)
    ttk.Button(both, text="X+U+ ▶", style="Jog.TButton", command=lambda: jog({"X": +1, "U": +1})).grid(row=1, column=2, padx=2)
    ttk.Button(both, text="▼ Y−V−", style="Jog.TButton", command=lambda: jog({"Y": -1, "V": -1})).grid(row=2, column=1, pady=2)
    both.grid(row=0, column=1, padx=8, sticky="n")
    pad(pads, "Turm 2  (U / V)", "U", "V").grid(row=0, column=2, padx=8, sticky="n")

    # -- actions ----------------------------------------------------------
    act = ttk.Frame(root, padding=8)
    act.pack(fill="x")

    def stop():
        if not worker:
            return
        if streaming["on"]:
            worker.abort_stream()
            log("> STOP Programm")
        else:
            worker.submit("raw", b"\x85")     # jog cancel: flushes queued jogs
            log("> STOP (jog cancel)")

    def reset():
        if worker:
            worker.submit("raw", b"\x18")
        log("> Soft-Reset")

    def set_ref():
        send(model.set_reference())

    def save_travel(axis):
        v = model.record_travel(axis)
        machine.save(machine_path)
        log(f"Verfahrweg {axis} = {v:g} mm gespeichert ({machine_path})")

    def home():
        if not worker:
            return
        if not machine.homing.enabled:
            log("! Endschalter nicht konfiguriert - Knopf 'Endschalter…'")
            return
        worker.submit("home")

    def open_homing():
        from .gui_homing import open_homing_window
        open_homing_window(root, machine, machine_path, lambda: worker, log, refresh_homing)

    def refresh_homing():
        """After the calibration dialog saved: push settings, relabel."""
        if worker:
            worker.homing = machine.homing
            worker.settings = standard_settings(machine)
            worker.submit("sync")
        home_btn.config(state="normal" if machine.homing.enabled else "disabled")

    ttk.Button(act, text="STOP", style="Act.TButton", command=stop).pack(side="left", padx=2)
    ttk.Button(act, text="$X entsperren", style="Act.TButton", command=lambda: send("$X")).pack(side="left", padx=2)
    ttk.Button(act, text="Reset", style="Act.TButton", command=reset).pack(side="left", padx=2)
    ttk.Separator(act, orient="vertical").pack(side="left", fill="y", padx=8)
    home_btn = ttk.Button(act, text="Referenzfahrt ($H)", style="Act.TButton", command=home,
                          state="normal" if machine.homing.enabled else "disabled")
    home_btn.pack(side="left", padx=2)
    ttk.Button(act, text="Endschalter…", style="Act.TButton", command=open_homing).pack(side="left", padx=2)
    ttk.Button(act, text="Referenz hier setzen (0/0/0/0)", style="Act.TButton", command=set_ref).pack(side="left", padx=2)
    ttk.Button(act, text="zur Referenz", style="Act.TButton", command=lambda: send(model.goto_reference())).pack(side="left", padx=2)
    ttk.Separator(act, orient="vertical").pack(side="left", fill="y", padx=8)
    ttk.Label(act, text="Verfahrweg = hier:").pack(side="left")
    for a in AXES:
        ttk.Button(act, text=a, width=3, command=lambda a=a: save_travel(a)).pack(side="left", padx=1)

    # -- hot wire ---------------------------------------------------------
    wire = ttk.LabelFrame(root, text="Heizdraht", padding=8)
    wire.pack(fill="x", padx=8, pady=(0, 8))
    power_var = tk.IntVar(value=machine.wire_power or 0)
    ttk.Scale(wire, from_=0, to=255, orient="horizontal", variable=power_var,
              command=lambda v: power_lbl.config(text=f"S{int(float(v))}")).pack(side="left", fill="x", expand=True)
    power_lbl = ttk.Label(wire, text=f"S{power_var.get()}", width=5)
    power_lbl.pack(side="left")
    ttk.Button(wire, text="Draht AN", command=lambda: send(model.hotwire(power_var.get()))).pack(side="left", padx=4)
    ttk.Button(wire, text="Draht AUS", command=lambda: send("M5")).pack(side="left")

    # -- program ----------------------------------------------------------
    from tkinter import filedialog, messagebox

    prog_frame = ttk.LabelFrame(root, text="G-Code", padding=8)
    prog_frame.pack(fill="x", padx=8, pady=(0, 8))
    program: dict = {"raw": "", "lines": [], "name": "", "problems": []}
    fmt_var = tk.StringVar(value="auto")
    prog_name = tk.StringVar(value="keine Datei geladen")
    prog_line = tk.StringVar(value="")
    progress = ttk.Progressbar(prog_frame, mode="determinate")
    streaming = {"on": False, "paused": False}

    def load_file():
        path = filedialog.askopenfilename(
            title="G-Code laden",
            filetypes=[("G-Code", "*.nc *.gcode *.ngc *.txt"), ("alle", "*")],
            initialdir=str(Path("gcode").resolve()) if Path("gcode").exists() else None)
        if not path:
            return
        program["raw"] = Path(path).read_text(errors="replace")
        program["name"] = Path(path).name
        log(f"--- {path}")
        prepare()

    def prepare():
        """Translate with the current format / wire setting and re-check."""
        if not program["raw"]:
            return
        text, notes = gc.translate(program["raw"], preset=fmt_var.get(),
                                   wire_power=power_var.get() or None,
                                   default_feed=machine.cut_feed)
        prog = gc.Program.parse(text)
        problems = machine.check_extents(prog.extents()) if machine.has_travel() else []
        program.update(lines=text.splitlines(), problems=list(prog.errors) + problems)
        prog_name.set(f"{program['name']}  ({len(prog.moves)} Bewegungen)")
        for n in notes:
            log(f"  umgesetzt: {n}")
        for l in prog.report().splitlines():
            log("  " + l)
        for pr in problems:
            log(f"  VERFAHRWEG: {pr}")
        if not machine.has_travel():
            log("  (Verfahrweg nicht vermessen - keine Bereichspruefung)")
        start_btn.config(state="normal")
        sim_btn.config(state="normal")
        progress.config(value=0, maximum=max(1, len(program["lines"])))
        prog_line.set("")

    def start():
        if not worker or not program["raw"]:
            return
        prepare()                       # picks up the current wire slider
        if program["problems"]:
            if not messagebox.askyesno("Probleme", "\n".join(program["problems"][:8])
                                       + "\n\nTrotzdem starten?"):
                return
        if not messagebox.askyesno("Start", f"{program['name']}\n\n"
                                   "Dieses Programm abspielen?\n"
                                   "Referenz gesetzt? Drahtleistung eingestellt?"):
            return
        streaming.update(on=True, paused=False)
        start_btn.config(state="disabled")
        pause_btn.config(state="normal", text="Pause")
        stop_btn.config(state="normal")
        worker.submit("stream", list(program["lines"]))
        log(f"> Start {program['name']}")

    def pause():
        if not worker or not streaming["on"]:
            return
        if streaming["paused"]:
            worker.submit("raw", b"~")
            streaming["paused"] = False
            pause_btn.config(text="Pause")
            log("> weiter (~)")
        else:
            worker.submit("raw", b"!")
            streaming["paused"] = True
            pause_btn.config(text="Weiter")
            log("> Pause (!)  - Draht bleibt an, Vorschub steht")

    def stop_program():
        if worker:
            worker.abort_stream()
        log("> STOP Programm (Feed-Hold + Reset, Draht aus)")

    def take_gcode(code: str, name: str):
        program["raw"] = code
        program["name"] = name
        log(f"--- Fluegel: {name}")
        prepare()

    def open_wing():
        from .gui_wing import open_wing_window
        open_wing_window(root, machine, Path("airfoil"), take_gcode, log)

    def open_sim():
        if not program["lines"]:
            log("! erst ein Programm laden")
            return
        from .gui_sim import open_sim_window
        open_sim_window(root, program["lines"], machine, program["name"])

    row = ttk.Frame(prog_frame)
    row.pack(fill="x")
    ttk.Button(row, text="Datei…", style="Act.TButton", command=load_file).pack(side="left")
    ttk.Button(row, text="Flügel…", style="Act.TButton", command=open_wing).pack(side="left", padx=(4, 0))
    ttk.Label(row, text="Format").pack(side="left", padx=(8, 2))
    fmt_box = ttk.Combobox(row, textvariable=fmt_var, width=7, state="readonly",
                           values=["auto", *gc.AXIS_PRESETS])
    fmt_box.pack(side="left")
    fmt_box.bind("<<ComboboxSelected>>", lambda e: prepare())
    ttk.Label(row, textvariable=prog_name, font=big).pack(side="left", padx=8)
    stop_btn = ttk.Button(row, text="STOP", style="Act.TButton", command=stop_program, state="disabled")
    stop_btn.pack(side="right", padx=2)
    sim_btn = ttk.Button(row, text="Simulation", style="Act.TButton", command=open_sim, state="disabled")
    sim_btn.pack(side="right", padx=(2, 12))
    pause_btn = ttk.Button(row, text="Pause", style="Act.TButton", command=pause, state="disabled")
    pause_btn.pack(side="right", padx=2)
    start_btn = ttk.Button(row, text="Start", style="Act.TButton", command=start, state="disabled")
    start_btn.pack(side="right", padx=2)
    progress.pack(fill="x", pady=(6, 2))
    ttk.Label(prog_frame, textvariable=prog_line, font=mono).pack(anchor="w")

    def stream_finished(ok: bool):
        streaming.update(on=False, paused=False)
        start_btn.config(state="normal" if program["lines"] else "disabled")
        pause_btn.config(state="disabled", text="Pause")
        stop_btn.config(state="disabled")
        log("Programm fertig." if ok else "Programm abgebrochen.")
        if ok and worker:
            worker.submit("line", "M5")

    # -- log --------------------------------------------------------------
    logbox = tk.Text(root, height=6, font=mono, state="disabled")
    logbox.pack(fill="x", padx=8, pady=(0, 8))

    def log(text: str):
        logbox.configure(state="normal")
        logbox.insert("end", text + "\n")
        logbox.see("end")
        logbox.configure(state="disabled")

    # -- connection handling ----------------------------------------------
    def connect():
        nonlocal worker
        if worker:
            worker.stop()
            worker = None
            conn_btn.config(text="Verbinden")
            state_var.set("getrennt")
            return
        worker = GrblWorker(port_var.get(), baud, settings=standard_settings(machine),
                            homing=machine.homing)
        worker.start()
        conn_btn.config(text="Trennen")
        state_var.set("verbinde…")

    conn_btn.config(command=connect)

    def pump():
        nonlocal worker
        if worker:
            while True:
                try:
                    kind, payload = worker.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "banner":
                    for l in payload:
                        if l:
                            log(f"< {l}")
                elif kind == "status":
                    state_var.set(payload["state"])
                    pressed = [c for c in payload.get("pn", "") if c in AXES]
                    pins_var.set(("Endschalter: " + " ".join(pressed)) if pressed else "")
                    mpos.update(payload.get("mpos", {}))
                    for a in AXES:
                        model.wpos[a] = mpos[a] - wco[a]
                        pos_vars[a].set(f"{model.wpos[a]:9.3f}")
                elif kind == "offset":
                    wco.update(payload)
                elif kind == "reply":
                    for l in payload:
                        log(f"< {l}")
                elif kind == "error":
                    log(f"! {payload}")
                elif kind == "progress":
                    i, n, line = payload
                    progress.config(value=i, maximum=n)
                    prog_line.set(f"{i}/{n}  {line}")
                elif kind == "stream_done":
                    stream_finished(payload)
                elif kind == "sent":
                    log(f"> {payload}")
                elif kind == "needs_homing":
                    log("! Position unbekannt - Referenzfahrt ($H) noetig, bis dahin bleibt grbl im Alarm")
                    for a in AXES:
                        pos_vars[a].set("?")
                elif kind == "homed":
                    log("Referenzfahrt fertig. Maschinenposition am Schalter: "
                        + "  ".join(f"{a}{v:.3f}" for a, v in payload.items()))
                    log("Arbeitsnull = Schalter + Versatz gesetzt (G54).")
                    machine.save(machine_path)
                elif kind == "reset":
                    log("! Board wurde zurueckgesetzt - Position unbekannt, "
                        + ("Referenzfahrt noetig" if machine.homing.enabled else "Referenz neu setzen"))
                    for a in AXES:
                        pos_vars[a].set("?")
                    if streaming["on"]:
                        stream_finished(False)
                elif kind == "closed":
                    worker = None
                    conn_btn.config(text="Verbinden")
                    state_var.set("getrennt")
                    break
        root.after(100, pump)

    def on_close():
        if worker:
            worker.submit("line", "M5")
            worker.stop()
        machine.jog_feed = model.feed_h
        machine.wire_power = power_var.get()
        machine.save(machine_path)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(100, pump)
    if autoconnect:
        root.after(200, connect)
    root.foamcut = {"open_sim": open_sim, "open_wing": open_wing, "open_homing": open_homing,
                    "load_program": take_gcode, "program": program}
    return root
