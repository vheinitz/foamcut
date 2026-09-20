"""Wing window: spec text on the left, preview on the right, G-code out.

Preview, two views on tk canvases (no matplotlib needed):
  front  X/Y plane - root and tip profile, the carriage paths of both towers
         (what the machine really travels, and what must fit the travel), the
         entry point, the block, the reference at 0/0
  top    X over span - towers, block, root and tip planes, LE and TE lines
"""
from __future__ import annotations

from pathlib import Path

from . import AXES
from . import gcode as gc
from .machine import Machine
from .wing import WingError, WingPath, WingSpec, generate, wing_name

COL = {"root": "#1f5fbf", "tip": "#1a9641", "t1": "#7aa6e0", "t2": "#8fd19e",
       "block": "#c8b27a", "face": "#8a5a00", "ref": "#c0392b", "entry": "#e67e22", "grid": "#e0e0e0"}


def _fit(canvas, xs, ys, pad=24):
    w = max(canvas.winfo_width(), 200)
    h = max(canvas.winfo_height(), 150)
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    sx = (w - 2 * pad) / max(x1 - x0, 1e-6)
    sy = (h - 2 * pad) / max(y1 - y0, 1e-6)
    s = min(sx, sy)
    ox = pad + ((w - 2 * pad) - (x1 - x0) * s) / 2
    oy = pad + ((h - 2 * pad) - (y1 - y0) * s) / 2

    def tr(x, y):
        return ox + (x - x0) * s, h - (oy + (y - y0) * s)
    return tr, s


def draw_front(canvas, path: WingPath, machine: Machine) -> None:
    canvas.delete("all")
    bx, by, bl, bh = path.block
    pts_all = path.root + path.tip + path.tower1 + path.tower2 + [(0, 0), (bx, by), (bx + bl, by + bh)]
    tr, s = _fit(canvas, [p[0] for p in pts_all], [p[1] for p in pts_all])

    # travel limits, if measured
    if machine.has_travel():
        for axis_h, axis_v, col in (("X", "Y", COL["t1"]), ("U", "V", COL["t2"])):
            x1, y1 = tr(machine.travel_mm[axis_h], machine.travel_mm[axis_v])
            x0, y0 = tr(0, 0)
            canvas.create_rectangle(x0, y0, x1, y1, outline=col, dash=(2, 4))
    # block
    canvas.create_rectangle(*tr(bx, by), *tr(bx + bl, by + bh), outline=COL["block"], width=2)
    # paths
    for pts, col, width, dash in ((path.tower1, COL["t1"], 1, (4, 3)), (path.tower2, COL["t2"], 1, (4, 3)),
                                  (path.root, COL["root"], 2, ()), (path.tip, COL["tip"], 2, ())):
        flat = [c for p in pts for c in tr(*p)]
        canvas.create_line(*flat, fill=col, width=width, dash=dash or None)
    # what the wire cuts at the two block faces - the sections you can measure
    for s_face, pts in path.faces:
        flat = [c for p in pts for c in tr(*p)]
        canvas.create_line(*flat, fill=COL["face"], width=2, dash=(6, 3))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x, y = tr(max(xs), max(ys))
        canvas.create_text(x + 4, y, anchor="w", fill=COL["face"], font=("TkDefaultFont", 9),
                           text=f"s={s_face:g}: {max(xs) - min(xs):.0f} x {max(ys) - min(ys):.1f}")
    # entry / lead lines
    for a, b, col in ((path.entry_t1, path.tower1[0], COL["t1"]), (path.entry_t2, path.tower2[0], COL["t2"]),
                      (path.entry_root, path.root[0], COL["root"]), (path.entry_tip, path.tip[0], COL["tip"])):
        canvas.create_line(*tr(*a), *tr(*b), fill=col, dash=(1, 3))
    for p in (path.entry_t1, path.entry_t2):
        x, y = tr(*p)
        canvas.create_oval(x - 4, y - 4, x + 4, y + 4, outline=COL["entry"], width=2)
    # reference
    x, y = tr(0, 0)
    canvas.create_line(x - 8, y, x + 8, y, fill=COL["ref"], width=2)
    canvas.create_line(x, y - 8, x, y + 8, fill=COL["ref"], width=2)
    canvas.create_text(x + 10, y - 10, text="0/0", fill=COL["ref"], anchor="w")
    # legend
    lx, ly = 8, 8
    for label, col in (("Wurzel", COL["root"]), ("Ende", COL["tip"]),
                       ("Schnitt an Blockflaechen", COL["face"]),
                       ("Turm 1 X/Y", COL["t1"]), ("Turm 2 U/V", COL["t2"]), ("Block", COL["block"])):
        canvas.create_line(lx, ly + 6, lx + 18, ly + 6, fill=col, width=2)
        canvas.create_text(lx + 22, ly + 6, text=label, anchor="w")
        ly += 16
    canvas.create_text(canvas.winfo_width() - 8, 8, anchor="ne", fill="#666",
                       text=f"Vorderansicht  X vorne ->  Y oben ^   {s * 100:.0f} px/100 mm")


def draw_top(canvas, path: WingPath, spec: WingSpec) -> None:
    canvas.delete("all")
    gap = path.tower_gap
    bx, by, bl, bh = path.block
    xs = [0, bx, bx + bl] + [p[0] for p in path.tower1 + path.tower2]
    ss = [0, gap]
    tr, s = _fit(canvas, xs, ss)
    x_min, x_max = min(xs), max(xs)
    # towers
    for sv, label, col in ((0, "Turm 1 (X/Y)", COL["t1"]), (gap, "Turm 2 (U/V)", COL["t2"])):
        canvas.create_line(*tr(x_min, sv), *tr(x_max, sv), fill=col, width=3)
        canvas.create_text(*tr(x_min, sv), text=label, anchor="sw", fill=col)
    # block where it really is along the span
    s_lo, s_hi = sorted(path.block_s)
    canvas.create_rectangle(*tr(bx, s_lo), *tr(bx + bl, s_hi), outline=COL["block"], width=2)
    for s_face, pts in path.faces:
        x_te, x_le = min(p[0] for p in pts), max(p[0] for p in pts)
        canvas.create_line(*tr(x_te, s_face), *tr(x_le, s_face), fill=COL["face"], width=2, dash=(6, 3))
    # root and tip planes with chord lines
    for sv, pts, col, label in ((path.s_root, path.root, COL["root"], "Wurzel"),
                                (path.s_tip, path.tip, COL["tip"], "Ende")):
        x_te, x_le = min(p[0] for p in pts), max(p[0] for p in pts)
        canvas.create_line(*tr(x_te, sv), *tr(x_le, sv), fill=col, width=3)
        canvas.create_text(*tr(x_le, sv), text=f" {label}", anchor="w", fill=col)
    # LE / TE lines root->tip, extended to the towers
    for pick in (min, max):
        xr = pick(p[0] for p in path.root)
        xt = pick(p[0] for p in path.tip)
        x1 = pick(p[0] for p in path.tower1)
        x2 = pick(p[0] for p in path.tower2)
        canvas.create_line(*tr(x1, 0), *tr(xr, path.s_root), *tr(xt, path.s_tip), *tr(x2, gap),
                           fill="#555", dash=(3, 3))
    # reference
    x, y = tr(0, 0)
    canvas.create_line(x, y - 6, x, y + 6, fill=COL["ref"], width=2)
    canvas.create_text(canvas.winfo_width() - 8, canvas.winfo_height() - 8, anchor="se", fill="#666",
                       text="Draufsicht  X vorne ->  Spannrichtung ^")


def open_wing_window(parent, machine: Machine, airfoil_dir: Path, on_gcode, log=print):
    import tkinter as tk
    from tkinter import filedialog, ttk

    from .wing import FIELDS, from_text, to_text

    win = tk.Toplevel(parent)
    win.title("foamcut wing")
    win.minsize(1280, 760)
    small = ("TkDefaultFont", 9)
    bold = ("TkDefaultFont", 10, "bold")

    outer = ttk.Frame(win, padding=8)
    outer.pack(side="left", fill="y")
    right = ttk.Frame(win, padding=8)
    right.pack(side="right", fill="both", expand=True)

    # -- form -------------------------------------------------------------
    form_canvas = tk.Canvas(outer, width=560, highlightthickness=0)
    form_scroll = ttk.Scrollbar(outer, orient="vertical", command=form_canvas.yview)
    form = ttk.Frame(form_canvas)
    form.bind("<Configure>", lambda e: form_canvas.configure(scrollregion=form_canvas.bbox("all")))
    form_canvas.create_window((0, 0), window=form, anchor="nw")
    form_canvas.configure(yscrollcommand=form_scroll.set)
    form_canvas.pack(side="left", fill="both", expand=True)
    form_scroll.pack(side="left", fill="y")

    airfoils = sorted(p.name for p in airfoil_dir.glob("*.dat")) if airfoil_dir.exists() else []
    vars_: dict[str, tk.StringVar] = {}
    entries: dict[str, tk.Widget] = {}
    row = 0

    # machine-level: the one number the wizards never measure
    ttk.Label(form, text="Maschine", font=bold).grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 2))
    row += 1
    gap_var = tk.StringVar(value=f"{machine.tower_gap_mm:g}")
    ttk.Label(form, text="Turmabstand").grid(row=row, column=0, sticky="w", padx=(4, 8))
    gap_entry = ttk.Entry(form, textvariable=gap_var, width=10, justify="right")
    gap_entry.grid(row=row, column=1, sticky="w")
    ttk.Label(form, text="mm", width=7).grid(row=row, column=2, sticky="w")
    row += 1
    gap_help = tk.StringVar()

    def gap_help_text():
        gap_help.set("Abstand der beiden Drahtaufhaengungen (Schlittenebenen), mit dem Massband gemessen. "
                     "Wird in machine.json gespeichert."
                     + ("" if machine.tower_gap_measured else "   NOCH NICHT GEMESSEN - 800 ist ein Platzhalter!"))
    gap_help_text()
    ttk.Label(form, textvariable=gap_help, font=small, foreground="#b00", wraplength=520,
              justify="left").grid(row=row, column=0, columnspan=3, sticky="w", padx=(16, 0), pady=(0, 3))
    row += 1
    for section, title, fields in FIELDS:
        ttk.Label(form, text=title, font=bold).grid(row=row, column=0, columnspan=3,
                                                     sticky="w", pady=(10, 2))
        row += 1
        for key, label, unit, default, help_, kind in fields:
            var = tk.StringVar(value=default)
            vars_[key] = var
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(4, 8))
            if kind == "airfoil":
                w = ttk.Combobox(form, textvariable=var, values=airfoils, width=16)
            elif kind == "bool":
                w = ttk.Frame(form)
                ttk.Radiobutton(w, text="nein", value="nein", variable=var).pack(side="left")
                ttk.Radiobutton(w, text="ja", value="ja", variable=var).pack(side="left", padx=(8, 0))
            else:
                w = ttk.Entry(form, textvariable=var, width=10, justify="right")
            w.grid(row=row, column=1, sticky="w")
            entries[key] = w
            ttk.Label(form, text=unit, width=7).grid(row=row, column=2, sticky="w")
            row += 1
            ttk.Label(form, text=help_, font=small, foreground="#555", wraplength=520,
                      justify="left").grid(row=row, column=0, columnspan=3, sticky="w", padx=(16, 0), pady=(0, 3))
            row += 1

    # -- result / status -------------------------------------------------
    status = tk.Text(outer, width=44, height=12, font=("TkFixedFont", 9), state="disabled",
                     wrap="word", relief="flat", background=win.cget("background"))
    status.pack(side="left", fill="y", padx=(8, 0))

    def say(lines, error=False):
        status.configure(state="normal")
        status.delete("1.0", "end")
        status.insert("1.0", "\n".join(lines))
        status.tag_configure("err", foreground="#b00")
        if error:
            status.tag_add("err", "1.0", "end")
        status.configure(state="disabled")

    # -- previews ---------------------------------------------------------
    front = tk.Canvas(right, bg="white", height=380)
    front.pack(fill="both", expand=True)
    top = tk.Canvas(right, bg="white", height=230)
    top.pack(fill="both", expand=True, pady=(8, 0))

    state = {"spec": None, "path": None, "gcode": "", "sent": None, "job": None}
    stale_var = tk.StringVar(value="")

    def values() -> dict[str, str]:
        return {k: v.get().strip() for k, v in vars_.items()}

    def mark_fields(bad: set[str]):
        for key, w in entries.items():
            if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox):
                w.configure(style="Bad.TEntry" if key in bad else "TEntry")

    style = ttk.Style(win)
    style.configure("Bad.TEntry", fieldbackground="#ffd6d6")

    def build() -> bool:
        vals = values()
        bad = set()
        try:
            gap = float(gap_var.get().replace(",", "."))
            if gap <= 0:
                raise ValueError
            if abs(gap - machine.tower_gap_mm) > 1e-9:
                machine.tower_gap_mm = gap
                machine.tower_gap_measured = True
                machine.save()
                gap_help_text()
                log(f"Turmabstand {gap:g} mm gespeichert (machine.json)")
        except ValueError:
            say(["Turmabstand: keine gueltige Zahl"], error=True)
            return False
        for key, (label, unit, default, help_, kind) in _catalogue().items():
            v = vals[key]
            if kind in ("num", "int") and v:
                try:
                    float(v.replace(",", "."))
                except ValueError:
                    bad.add(key)
        mark_fields(bad)
        if bad:
            say([f"Keine Zahl: {', '.join(_catalogue()[k][0] for k in sorted(bad))}"], error=True)
            state.update(spec=None, path=None, gcode="")
            return False
        try:
            spec = WingSpec.parse(to_text(vals))
            code, path = generate(spec, machine, airfoil_dir)
        except (WingError, ValueError, OSError) as e:
            say([f"Fehler: {e}"], error=True)
            state.update(spec=None, path=None, gcode="")
            return False
        state.update(spec=spec, path=path, gcode=code)
        prog = gc.Program.parse(code)
        problems = machine.check_extents(path.extents()) if machine.has_travel() else []
        ext = path.extents()
        lines = ["Ergebnis", ""]
        lines += path.notes
        lines.append("")
        lines.append("Schlittenweg (muss in den Verfahrweg passen):")
        for a, (lo, hi) in ext.items():
            tr = machine.travel_mm.get(a, 0)
            lines.append(f"  {a}: {lo:7.1f} .. {hi:7.1f} mm" + (f"   (max {tr:g})" if tr else ""))
        for p in problems:
            lines.append(f"VERFAHRWEG: {p}")
        for e in prog.errors:
            lines.append(f"FEHLER: {e}")
        if state["sent"] is not None and state["sent"] != code:
            stale_var.set("Programm im Hauptfenster ist VERALTET - erneut uebergeben")
        say(lines, error=bool(problems or prog.errors))
        win.update_idletasks()
        draw_front(front, path, machine)
        draw_top(top, path, spec)
        return not (problems or prog.errors)

    def schedule_build(*_):
        if state["job"]:
            win.after_cancel(state["job"])
        state["job"] = win.after(250, build)

    for var in vars_.values():
        var.trace_add("write", schedule_build)
    gap_var.trace_add("write", schedule_build)

    def load():
        p = filedialog.askopenfilename(title="Fluegel laden", filetypes=[("wing", "*.wing"), ("alle", "*")])
        if p:
            for key, v in from_text(Path(p).read_text()).items():
                vars_[key].set(v)

    def save():
        p = filedialog.asksaveasfilename(title="Fluegel speichern", defaultextension=".wing",
                                         filetypes=[("wing", "*.wing")])
        if p:
            Path(p).write_text(to_text(values()))
            log(f"Fluegel gespeichert: {p}")

    def to_program():
        ok = build()
        if not state["gcode"]:
            stale_var.set("NICHT uebergeben - Eingabefehler, siehe Ergebnis")
            log("! Fluegel: nicht uebergeben, Eingabefehler")
            return
        s = state["spec"]
        name = wing_name(s)
        state["sent"] = state["gcode"]
        on_gcode(state["gcode"], name)
        if ok:
            stale_var.set(f"uebergeben: {name}")
            log(f"Fluegel-G-Code uebernommen: {name}")
        else:
            # Hand it over anyway - the main window's Start asks again - but
            # never let a refusal look like success.
            stale_var.set(f"uebergeben MIT WARNUNGEN: {name} - siehe Ergebnis")
            log(f"! Fluegel-G-Code uebernommen, aber Verfahrweg/Fehler gemeldet: {name}")

    def save_gcode():
        build()
        if not state["gcode"]:
            stale_var.set("NICHT gespeichert - Eingabefehler, siehe Ergebnis")
            return
        p = filedialog.asksaveasfilename(title="G-Code speichern", defaultextension=".nc",
                                         filetypes=[("G-Code", "*.nc")])
        if p:
            Path(p).write_text(state["gcode"])
            log(f"G-Code gespeichert: {p}")
            # what is on disk is also what the main window runs - no stale copy
            state["sent"] = state["gcode"]
            on_gcode(state["gcode"], Path(p).name)
            stale_var.set(f"gespeichert UND uebergeben: {Path(p).name}")

    bar = ttk.Frame(win, padding=(8, 4))
    bar.pack(side="bottom", fill="x", before=outer)
    ttk.Button(bar, text="Laden…", command=load).pack(side="left")
    ttk.Button(bar, text="Speichern…", command=save).pack(side="left", padx=4)
    ttk.Label(bar, textvariable=stale_var, foreground="#b00", font=bold).pack(side="left", padx=16)
    ttk.Button(bar, text="G-Code speichern…", command=save_gcode).pack(side="right")
    ttk.Button(bar, text="→ Programm", command=to_program).pack(side="right", padx=4)

    win.bind("<Configure>", lambda e: (state["path"] and draw_front(front, state["path"], machine),
                                       state["path"] and draw_top(top, state["path"], state["spec"])))
    win.after(200, build)
    return win


def _catalogue():
    from .wing import field_catalogue
    return field_catalogue()
