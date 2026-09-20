"""Endschalter calibration dialog.

    1. Switch type, pull-off, speeds  -> grbl $5 $27 $24 $25
    2. Referenzfahrt ($H)             -> the machine finds the switches
    3. Per axis: jog in + until the axis is where zero should be (e.g. until
       the wire is level), press "= aktuelle Position": that is the offset.
       Or just type it.
    4. Per axis: usable length from the switch, typed in - no need to drive.
    5. Speichern: machine.json + board settings + G54, kept until the next
       calibration.
"""
from __future__ import annotations

from pathlib import Path

from . import AXES
from .machine import Machine


def open_homing_window(parent, machine: Machine, machine_path: Path, get_worker, log, on_saved):
    import tkinter as tk
    from tkinter import ttk

    h = machine.homing
    win = tk.Toplevel(parent)
    win.title("foamcut Endschalter")
    win.minsize(720, 560)
    small = ("TkDefaultFont", 9)
    bold = ("TkDefaultFont", 10, "bold")
    f = ttk.Frame(win, padding=12)
    f.pack(fill="both", expand=True)

    def help_(text, row, col=0, span=4):
        ttk.Label(f, text=text, font=small, foreground="#555", wraplength=660, justify="left") \
            .grid(row=row, column=col, columnspan=span, sticky="w", padx=(12, 0), pady=(0, 6))

    r = 0
    enabled = tk.BooleanVar(value=h.enabled)
    ttk.Checkbutton(f, text="Endschalter verwenden (Referenzfahrt statt Ecke von Hand)",
                    variable=enabled).grid(row=r, column=0, columnspan=4, sticky="w")
    r += 1
    help_("Alle vier Schalter sitzen am negativen Ende: X/U hinten, Y/V unten. Der V-Schalter "
          "gehoert an EXP2 Pin 7 (D38), siehe docs/gt2560_pinout.md.", r); r += 1

    ttk.Label(f, text="Schalterart", font=bold).grid(row=r, column=0, sticky="w", pady=(8, 0)); r += 1
    nc = tk.BooleanVar(value=h.invert_switch)
    ttk.Radiobutton(f, text="Schliesser (NO): offen, bis er gedrueckt wird", value=False, variable=nc) \
        .grid(row=r, column=0, columnspan=4, sticky="w"); r += 1
    ttk.Radiobutton(f, text="Oeffner (NC): geschlossen, oeffnet beim Druecken - sicherer bei Kabelbruch",
                    value=True, variable=nc).grid(row=r, column=0, columnspan=4, sticky="w"); r += 1

    ttk.Label(f, text="Fahrt", font=bold).grid(row=r, column=0, sticky="w", pady=(8, 0)); r += 1
    pulloff = tk.StringVar(value=f"{h.pulloff:g}")
    seek = tk.StringVar(value=f"{h.seek:g}")
    feed = tk.StringVar(value=f"{h.feed:g}")
    for label, var, unit, text in (
            ("Pull-off", pulloff, "mm", "So weit faehrt jede Achse nach dem Ausloesen wieder vom Schalter weg. "
                                        "Dort ist die Maschinenposition 'Schalter'."),
            ("Suchgeschwindigkeit", seek, "mm/min", "Erste, schnelle Anfahrt bis zum Schalter (grbl begrenzt je Achse)."),
            ("Referenzgeschwindigkeit", feed, "mm/min", "Zweite, langsame Anfahrt - bestimmt die Wiederholgenauigkeit.")):
        ttk.Label(f, text=label).grid(row=r, column=0, sticky="w")
        ttk.Entry(f, textvariable=var, width=8, justify="right").grid(row=r, column=1, sticky="w")
        ttk.Label(f, text=unit).grid(row=r, column=2, sticky="w")
        r += 1
        help_(text, r); r += 1

    ttk.Label(f, text="Achsen", font=bold).grid(row=r, column=0, sticky="w", pady=(8, 0)); r += 1
    help_("Versatz: so weit in + liegt der Arbeitsnullpunkt hinter der Schalterposition (Pull-off). "
          "Damit gleichst du aus, dass die Schalter nicht exakt fluchten - z.B. den Draht waagerecht stellen. "
          "Laenge: nutzbarer Weg ab Schalter, von Hand eingegeben, nicht angefahren.", r); r += 1
    ttk.Label(f, text="Achse").grid(row=r, column=0, sticky="w")
    ttk.Label(f, text="Versatz + [mm]").grid(row=r, column=1, sticky="w")
    ttk.Label(f, text="").grid(row=r, column=2)
    ttk.Label(f, text="Laenge ab Schalter [mm]").grid(row=r, column=3, sticky="w")
    r += 1
    off_vars = {a: tk.StringVar(value=f"{h.offset_mm[a]:g}") for a in AXES}
    len_vars = {a: tk.StringVar(value=f"{h.length_mm[a]:g}") for a in AXES}
    names = {"X": "X  Turm 1 waagerecht", "Y": "Y  Turm 1 senkrecht",
             "U": "U  Turm 2 waagerecht", "V": "V  Turm 2 senkrecht"}

    def take_current(axis):
        w = get_worker()
        if not w:
            status.set("nicht verbunden")
            return
        if not h.home_mpos:
            status.set("erst Referenzfahrt, dann Position uebernehmen")
            return
        # ask the worker for a fresh status via the main window's position; simplest:
        # the last status the GUI saw is in parent's model, but we do not have it
        # here - so request one synchronously through a tiny queue round trip.
        import queue as _q
        got = _q.Queue()
        w.submit("probe_pos", got)
        try:
            mpos = got.get(timeout=3)
        except _q.Empty:
            status.set("keine Position vom Board")
            return
        off_vars[axis].set(f"{mpos[axis] - h.home_mpos[axis]:.3f}")
        status.set(f"{axis}: Versatz {off_vars[axis].get()} mm = aktuelle Position minus Schalter")

    for a in AXES:
        ttk.Label(f, text=names[a]).grid(row=r, column=0, sticky="w")
        ttk.Entry(f, textvariable=off_vars[a], width=8, justify="right").grid(row=r, column=1, sticky="w")
        ttk.Button(f, text="= aktuelle Position", command=lambda a=a: take_current(a)).grid(row=r, column=2, padx=6)
        ttk.Entry(f, textvariable=len_vars[a], width=8, justify="right").grid(row=r, column=3, sticky="w")
        r += 1

    pins = tk.StringVar(value="")

    def read_pins():
        w = get_worker()
        if not w:
            pins.set("nicht verbunden"); return
        import queue as _q
        got = _q.Queue()
        w.submit("probe_status", got)
        try:
            st = got.get(timeout=3)
        except _q.Empty:
            pins.set("keine Antwort vom Board"); return
        pressed = st.get("pn", "")
        axes = [c for c in pressed if c in AXES]
        pins.set(("gedrueckt: " + " ".join(axes)) if axes else "kein Schalter gedrueckt")
        pins.set(pins.get() + f"   (Pn:{pressed})" if pressed else pins.get())

    ttk.Button(f, text="Schalterzustand lesen", command=read_pins).grid(row=r, column=0, sticky="w", pady=(8, 0))
    ttk.Label(f, textvariable=pins).grid(row=r, column=1, columnspan=3, sticky="w", pady=(8, 0)); r += 1
    help_("Jeden Schalter von Hand druecken und lesen: es muss genau die richtige Achse erscheinen. "
          "Erscheint sie im losgelassenen Zustand, ist die Schalterart falsch herum.", r); r += 1

    status = tk.StringVar(value="")
    ttk.Label(f, textvariable=status, wraplength=660, justify="left", foreground="#b00").grid(
        row=r, column=0, columnspan=4, sticky="w", pady=(10, 0)); r += 1

    def read_form() -> list[str]:
        errors = []
        def num(var, name, lo=None):
            try:
                v = float(var.get().replace(",", "."))
            except ValueError:
                errors.append(f"{name}: keine Zahl"); return None
            if lo is not None and v < lo:
                errors.append(f"{name}: muss >= {lo:g} sein")
            return v
        h.enabled = enabled.get()
        h.invert_switch = nc.get()
        p = num(pulloff, "Pull-off", 0.5)
        s = num(seek, "Suchgeschwindigkeit", 10)
        fd = num(feed, "Referenzgeschwindigkeit", 5)
        offs = {a: num(off_vars[a], f"Versatz {a}", 0.0) for a in AXES}
        lens = {a: num(len_vars[a], f"Laenge {a}", 0.0) for a in AXES}
        if errors:
            return errors
        h.pulloff, h.seek, h.feed = p, s, fd
        h.offset_mm.update(offs)
        h.length_mm.update(lens)
        if h.enabled and any(h.length_mm[a] <= 0 for a in AXES):
            errors.append("Laenge ab Schalter fehlt fuer mindestens eine Achse")
        return errors

    def do_home():
        errs = read_form()
        if errs:
            status.set("\n".join(errs)); return
        w = get_worker()
        if not w:
            status.set("nicht verbunden"); return
        if not h.enabled:
            status.set("Endschalter zuerst aktivieren"); return
        machine.save(machine_path)
        on_saved()                       # pushes $22 etc. to the board first
        w.submit("home")
        status.set("Referenzfahrt laeuft - siehe Log im Hauptfenster")

    def save():
        errs = read_form()
        if errs:
            status.set("\n".join(errs)); return
        machine.save(machine_path)
        on_saved()
        w = get_worker()
        if w and h.enabled and h.home_mpos:
            # re-apply the work origin with the new offsets, no need to home again
            origin = h.work_origin(h.home_mpos)
            w.submit("line", "G10 L2 P1 " + " ".join(f"{a}{origin[a]:.3f}" for a in AXES))
            w.submit("line", "G54")
            w.submit("offset")
        status.set(f"gespeichert: {machine_path}   nutzbar: " +
                   "  ".join(f"{a} {h.usable_travel(a):.1f}" for a in AXES))
        log("Endschalter-Konfiguration gespeichert" + (" (aktiv)" if h.enabled else " (aus)"))

    bar = ttk.Frame(f)
    bar.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(12, 0))
    ttk.Button(bar, text="Referenzfahrt jetzt ($H)", command=do_home).pack(side="left")
    ttk.Button(bar, text="Speichern & aufs Board", command=save).pack(side="right")
    ttk.Button(bar, text="Schliessen", command=win.destroy).pack(side="right", padx=6)
    return win
