"""Simulation window: two coordinate systems side by side, X/Y and U/V.

The wire passage point of each tower walks the program like a turtle: rapids
grey and dashed, cuts in colour, the current position as a dot. Speed factor,
pause, single step, and "alles sofort".
"""
from __future__ import annotations

from . import AXES
from . import gcode as gc
from .machine import Machine
from .sim import Segment, bounds, segments, total_seconds

COL = {"cut1": "#1f5fbf", "cut2": "#1a9641", "rapid": "#b0b0b0", "turtle": "#e67e22",
       "travel": "#c8b27a", "axis": "#999", "text": "#444"}


class _View:
    """One canvas with a mm -> pixel transform and axis decoration."""

    def __init__(self, canvas, title: str, box, travel: tuple[float, float] | None, pad: int = 28):
        self.c = canvas
        self.title = title
        xmin, xmax, ymin, ymax = box
        if travel:
            xmax, ymax = max(xmax, travel[0]), max(ymax, travel[1])
        self.box = (xmin, xmax, ymin, ymax)
        self.travel = travel
        self.pad = pad
        self.s = 1.0
        self.ox = self.oy = 0.0

    def fit(self):
        w = max(self.c.winfo_width(), 200)
        h = max(self.c.winfo_height(), 150)
        xmin, xmax, ymin, ymax = self.box
        self.s = min((w - 2 * self.pad) / max(xmax - xmin, 1e-6),
                     (h - 2 * self.pad) / max(ymax - ymin, 1e-6))
        self.ox = self.pad + ((w - 2 * self.pad) - (xmax - xmin) * self.s) / 2 - xmin * self.s
        self.oy = h - (self.pad + ((h - 2 * self.pad) - (ymax - ymin) * self.s) / 2) + ymin * self.s

    def tr(self, x, y):
        return self.ox + x * self.s, self.oy - y * self.s

    def decorate(self):
        c = self.c
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        # grid every 10 / 50 mm
        xmin, xmax, ymin, ymax = self.box
        step = 10.0 if (xmax - xmin) < 300 else 50.0
        import math
        x = math.floor(xmin / step) * step
        while x <= xmax:
            px, _ = self.tr(x, 0)
            c.create_line(px, 0, px, h, fill="#eeeeee")
            x += step
        y = math.floor(ymin / step) * step
        while y <= ymax:
            _, py = self.tr(0, y)
            c.create_line(0, py, w, py, fill="#eeeeee")
            y += step
        # axes through the origin
        x0, y0 = self.tr(0, 0)
        c.create_line(0, y0, w, y0, fill=COL["axis"])
        c.create_line(x0, 0, x0, h, fill=COL["axis"])
        c.create_text(x0 + 4, y0 - 4, text="0", anchor="sw", fill=COL["axis"])
        if self.travel:
            c.create_rectangle(x0, y0, *self.tr(*self.travel), outline=COL["travel"], dash=(3, 3))
            c.create_text(*self.tr(self.travel[0], self.travel[1]), text="Verfahrweg ", anchor="ne",
                          fill=COL["travel"], font=("TkDefaultFont", 8))
        c.create_text(8, 8, anchor="nw", text=self.title, font=("TkDefaultFont", 11, "bold"), fill=COL["text"])
        c.create_text(w - 8, 8, anchor="ne", text=f"{step:g} mm Raster", fill=COL["axis"], font=("TkDefaultFont", 8))

    def segment(self, a, b, rapid: bool, colour: str):
        self.c.create_line(*self.tr(*a), *self.tr(*b), fill=COL["rapid"] if rapid else colour,
                           width=1 if rapid else 2, dash=(4, 3) if rapid else None, tags="path")

    def turtle(self, p, wire_on: bool):
        self.c.delete("turtle")
        x, y = self.tr(*p)
        r = 5
        self.c.create_oval(x - r, y - r, x + r, y + r, outline=COL["turtle"], width=2,
                           fill=COL["turtle"] if wire_on else "", tags="turtle")


def open_sim_window(parent, lines: list[str], machine: Machine, name: str = ""):
    import tkinter as tk
    from tkinter import ttk

    prog = gc.Program.parse("\n".join(lines))
    segs = segments(prog, rapid_feed=max(machine.max_rate.values()))
    box1, box2 = bounds(segs)
    total = total_seconds(segs)

    win = tk.Toplevel(parent)
    win.title(f"foamcut sim  {name}".rstrip())
    win.minsize(1000, 560)

    views_frame = ttk.Frame(win)
    views_frame.pack(fill="both", expand=True)
    c1 = tk.Canvas(views_frame, bg="white")
    c2 = tk.Canvas(views_frame, bg="white")
    c1.pack(side="left", fill="both", expand=True, padx=(8, 4), pady=8)
    c2.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)
    t1 = (machine.travel_mm["X"], machine.travel_mm["Y"]) if machine.has_travel() else None
    t2 = (machine.travel_mm["U"], machine.travel_mm["V"]) if machine.has_travel() else None
    v1 = _View(c1, "Turm 1   X →   Y ↑", box1, t1)
    v2 = _View(c2, "Turm 2   U →   V ↑", box2, t2)

    bar = ttk.Frame(win, padding=8)
    bar.pack(fill="x")
    state = {"i": 0, "running": False, "job": None, "speed": 10.0}
    info = tk.StringVar()
    speed_var = tk.DoubleVar(value=10.0)

    def redraw_all(upto: int):
        for v in (v1, v2):
            v.fit()
            v.decorate()
        for s in segs[:upto]:
            v1.segment(s.t1_start, s.t1_end, s.rapid, COL["cut1"])
            v2.segment(s.t2_start, s.t2_end, s.rapid, COL["cut2"])
        if segs:
            k = min(max(upto, 1), len(segs)) - 1
            p1 = segs[k].t1_end if upto else segs[0].t1_start
            p2 = segs[k].t2_end if upto else segs[0].t2_start
            on = segs[k].wire_on if upto else False
            v1.turtle(p1, on)
            v2.turtle(p2, on)
        show_info()

    def show_info():
        i = state["i"]
        if not segs:
            info.set("kein Programm")
            return
        done = sum(s.seconds for s in segs[:i])
        if i < len(segs):
            s = segs[i]
            pos = f"X{s.t1_start[0]:.2f} Y{s.t1_start[1]:.2f}   U{s.t2_start[0]:.2f} V{s.t2_start[1]:.2f}"
            kind = "Eilgang" if s.rapid else "Schnitt"
        else:
            s = segs[-1]
            pos = f"X{s.t1_end[0]:.2f} Y{s.t1_end[1]:.2f}   U{s.t2_end[0]:.2f} V{s.t2_end[1]:.2f}"
            kind = "Ende"
        info.set(f"Segment {i}/{len(segs)}   Zeile {s.line_no}   {kind}   {pos}   "
                 f"{done / 60:.1f} / {total / 60:.1f} min")

    def step():
        i = state["i"]
        if i >= len(segs):
            state["running"] = False
            run_btn.config(text="Start")
            return 0.0
        s = segs[i]
        v1.segment(s.t1_start, s.t1_end, s.rapid, COL["cut1"])
        v2.segment(s.t2_start, s.t2_end, s.rapid, COL["cut2"])
        v1.turtle(s.t1_end, s.wire_on)
        v2.turtle(s.t2_end, s.wire_on)
        state["i"] = i + 1
        show_info()
        return s.seconds

    def tick():
        if not state["running"]:
            return
        secs = step()
        if state["i"] >= len(segs):
            return
        delay = max(15, int(secs * 1000 / max(speed_var.get(), 0.1)))
        state["job"] = win.after(delay, tick)

    def run():
        if state["running"]:
            state["running"] = False
            run_btn.config(text="Start")
            return
        if state["i"] >= len(segs):
            state["i"] = 0
            redraw_all(0)
        state["running"] = True
        run_btn.config(text="Pause")
        tick()

    def reset():
        state["running"] = False
        run_btn.config(text="Start")
        if state["job"]:
            win.after_cancel(state["job"])
        state["i"] = 0
        redraw_all(0)

    def finish():
        state["running"] = False
        run_btn.config(text="Start")
        state["i"] = len(segs)
        redraw_all(len(segs))

    run_btn = ttk.Button(bar, text="Start", command=run)
    run_btn.pack(side="left")
    ttk.Button(bar, text="Schritt", command=lambda: (state["running"] or step())).pack(side="left", padx=4)
    ttk.Button(bar, text="Zurück", command=reset).pack(side="left")
    ttk.Button(bar, text="Alles sofort", command=finish).pack(side="left", padx=4)
    ttk.Label(bar, text="   Tempo").pack(side="left")
    ttk.Scale(bar, from_=1, to=100, orient="horizontal", variable=speed_var, length=160).pack(side="left")
    speed_lbl = ttk.Label(bar, text="10x", width=5)
    speed_lbl.pack(side="left")
    speed_var.trace_add("write", lambda *_: speed_lbl.config(text=f"{speed_var.get():.0f}x"))
    ttk.Label(bar, textvariable=info, font=("TkFixedFont", 10)).pack(side="left", padx=16)

    win.bind("<Configure>", lambda e: redraw_all(state["i"]) if e.widget is win else None)
    win.after(100, lambda: redraw_all(0))
    return win
