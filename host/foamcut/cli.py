"""foamcut - command line front end for the foam cutter bring-up.

The `check` and `gen` subcommands work without any hardware attached; the rest
need the board on a serial port.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import AXES, __version__
from . import gcode as gc
from . import hwtest as hwt
from . import setup as wiz
from .grbl import Grbl, GrblAlarm, GrblError
from . import homing as hm
from .machine import DEFAULT_PATH as MACHINE_PATH
from .machine import Machine
from .link import LinkError, find_port, list_ports, open_link

DEFAULT_PORT = "auto"


def _open(args) -> Grbl:
    link = open_link(args.port, args.baud)
    g = Grbl(link)
    banner = g.connect()
    for line in banner:
        print(f"< {line}")
    if not g.is_grbl():
        print("warning: no grbl banner - is the hwtest firmware still flashed?",
              file=sys.stderr)
    return g


# ------------------------------------------------------------ offline cmds --
def _travel_problems(prog, machine_path) -> list[str]:
    m = Machine.load_or_none(Path(machine_path))
    if m is None or not m.has_travel():
        return []
    return m.check_extents(prog.extents())


def _load_program(args, wire_power=None):
    """Read, translate (axis letters, G64, feed after G94, wire S) and parse."""
    raw = Path(args.file).read_text(errors="replace")
    m = Machine.load_or_none(Path(args.machine))
    default_feed = m.cut_feed if m else 300.0
    text, notes = gc.translate(raw, preset=args.format, wire_power=wire_power,
                               default_feed=default_feed)
    for n in notes:
        print(f"  umgesetzt: {n}")
    return text, gc.Program.parse(text)


def cmd_convert(args) -> int:
    """Write the grbl-ready translation of a generator's file."""
    text, prog = _load_program(args, wire_power=args.wire)
    Path(args.out).write_text(text)
    print(prog.report())
    print(f"geschrieben: {args.out}")
    return 1 if prog.errors else 0


def cmd_check(args) -> int:
    text, prog = _load_program(args)
    print(f"{args.file}:")
    print(prog.report())
    problems = _travel_problems(prog, args.machine)
    for p in problems:
        print(f"  VERFAHRWEG: {p}")
    return 1 if (prog.errors or problems) else 0


def cmd_gen(args) -> int:
    if args.what == "square":
        text = gc.gen_square(args.size, args.feed)
    elif args.what == "taper":
        text = gc.gen_taper(args.size, args.size / 2, args.size * 0.8, args.feed)
    else:
        text = gc.gen_axis_bounce(args.axis, args.size, args.feed)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


# ------------------------------------------------------------- online cmds --
def cmd_probe(args) -> int:
    """Say what is on the serial port, without assuming which firmware."""
    ports = list_ports()
    if not ports:
        print("kein serieller Port da.")
        print("  - USB-Kabel steckt? (Datenkabel, nicht nur Ladekabel)")
        print("  - 12/24 V Netzteil an?")
        print("  - Board-LEDs an? Wenn nicht, liegt es an der Versorgung.")
        return 1
    print("Ports: " + ", ".join(ports))
    port = find_port(args.port)
    print(f"pruefe {port} ...")
    try:
        link = open_link(port, args.baud)
    except LinkError as e:
        print(f"  {e}")
        return 1
    try:
        banner = [l for l in link.drain() if l]
        # '?' is answered by both firmwares in their own way: grbl with a
        # <...> status report, hwtest with its command list.
        # A DTR reset leaves junk bytes in the board's line buffer; an empty
        # line flushes them (both firmwares answer it with a plain 'ok').
        link.write_raw(b"\n")
        time.sleep(0.3)
        link.drain()
        link.write_raw(b"?\n")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            l = link.read_line(timeout=0.3)
            if l is None:
                continue
            banner.append(l)
            if l == "ok" or l.startswith("<"):
                break
        banner = [l for l in banner if l and not l.startswith("unknown command")]
        if not banner:
            print("  keine Antwort: der USB-Wandler meldet sich, der ATmega")
            print("  schweigt. Versorgung, USB-Kabel oder Bootloader pruefen -")
            print("  siehe docs/bringup.md, Abschnitt 'Board meldet sich nicht'.")
            return 1
        for line in banner[:3]:
            print(f"  < {line}")
        if any(l.startswith("Grbl") or l.startswith("<") for l in banner):
            print("  -> grbl laeuft. Weiter mit 'foamcut gui' oder 'foamcut selftest'.")
        elif any("foamcut hwtest" in l or l.startswith("commands:") for l in banner):
            print("  -> hwtest-Firmware laeuft. Weiter mit 'foamcut hwtest' oder 'make grbl-flash'.")
        else:
            print("  -> unbekannte Firmware (Marlin?).")
        return 0
    finally:
        link.close()


def cmd_status(args) -> int:
    g = _open(args)
    st = g.status()
    print(f"state: {st['state']}")
    for a, v in st.get("mpos", {}).items():
        print(f"  {a}: {v:9.3f}")
    g.link.close()
    return 0


def cmd_pins(args) -> int:
    """Watch the limit inputs: poll status reports and print every change of
    the Pn field. Press each switch in turn to learn which axis it is on."""
    g = _open(args)
    print(f"$5 (Schalter invertiert) = {g.settings().get(5, 0):g}   -"
          " Oeffner ohne $5=1 stehen dauerhaft in Pn, beim Druecken verschwindet der Buchstabe")
    print(f"beobachte {args.seconds:g} s, Strg-C beendet")
    last = None
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            st = g.status()
            pins = st.get("pn", "")
            if pins != last:
                stamp = time.strftime("%H:%M:%S")
                print(f"  {stamp}  Pn: {pins or '-':6}  ({st['state']})")
                last = pins
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass
    g.link.close()
    return 0


def cmd_settings(args) -> int:
    g = _open(args)
    if args.settings_action == "dump":
        for num, val in sorted(g.settings().items()):
            print(f"${num}={val:g}")
    else:
        applied = g.apply_settings(Path(args.file).read_text())
        for line in applied:
            print(f"> {line}")
        print(f"{len(applied)} settings applied")
    g.link.close()
    return 0


def cmd_jog(args) -> int:
    g = _open(args)
    axis = args.axis.upper()
    if axis not in AXES:
        print(f"axis must be one of {', '.join(AXES)}", file=sys.stderr)
        return 2
    g.command(f"$J=G91 G21 {axis}{args.distance:g} F{args.feed:g}")
    g.wait_idle(timeout=120)
    print(g.status()["mpos"])
    g.link.close()
    return 0


def cmd_wire(args) -> int:
    g = _open(args)
    g.hotwire(args.power)
    print(f"hot wire set to S{args.power}")
    g.link.close()
    return 0


def cmd_run(args) -> int:
    text, prog = _load_program(args, wire_power=args.wire)
    print(prog.report())
    problems = _travel_problems(prog, args.machine)
    for p in problems:
        print(f"  VERFAHRWEG: {p}")
    if (prog.errors or problems) and not args.force:
        print("refusing to run this file (use --force)", file=sys.stderr)
        return 1
    if problems:
        print("hinweis: Verfahrwegpruefung setzt voraus, dass Arbeitsnull der "
              "Referenzpunkt ist (foamcut ref)")

    g = _open(args)
    try:
        def show(i, line):
            print(f"[{i}] {line}")
        g.stream(text.splitlines(), progress=show if args.verbose else None)
        g.wait_idle()
        print("done")
    except (GrblError, GrblAlarm) as e:
        print(f"aborted: {e}", file=sys.stderr)
        g.link.write_raw(b"\x18")  # soft reset, stops motion and the hot wire
        return 1
    finally:
        g.link.close()
    return 0


def _wizard(args) -> tuple[Grbl, wiz.Wizard]:
    g = _open(args)
    if not g.is_grbl():
        g.link.close()
        raise LinkError("foamcut setup braucht grbl auf dem Board: make grbl-flash")
    m = Machine.load_or_none(Path(args.machine)) or Machine()
    axes = tuple(a.upper() for a in getattr(args, "axes", None) or AXES)
    bad = [a for a in axes if a not in AXES]
    if bad:
        g.link.close()
        raise LinkError(f"--axes: unbekannt {bad}, erlaubt X Y U V")
    w = wiz.Wizard(g, m, wiz.Console(), jog_mm=getattr(args, "jog_mm", 20.0), axes=axes)
    spmm = getattr(args, "spmm", None)
    if spmm:
        print(f"setze Startwert {spmm:g} Schritte/mm auf allen Achsen ($100..$103)")
        for i, a in enumerate(AXES):
            g.set_setting(100 + i, spmm)
            m.steps_per_mm[a] = spmm
    return g, w


def cmd_setup(args) -> int:
    """Measure the machine: mapping, steps/mm, direction, reference, travel."""
    g, w = _wizard(args)
    try:
        rc = w.run(phases=args.phases)
        if rc == 0:
            path = w.machine.save(Path(args.machine))
            print(f"gespeichert: {path}")
        return rc
    except wiz.Abort as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    finally:
        g.link.close()


def cmd_ref(args) -> int:
    """Manual referencing only - the thing to do after every power-up."""
    g, w = _wizard(args)
    try:
        w._prepare()
        w.phase_reference()
        return 0
    except wiz.Abort as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    finally:
        g.link.close()


def cmd_home(args) -> int:
    """Homing cycle on the switches, then the work origin from the offsets."""
    m = Machine.load_or_none(Path(args.machine))
    if not m or not m.homing.enabled:
        print("Endschalter sind nicht konfiguriert: foamcut homing set --enable ...", file=sys.stderr)
        return 1
    g = _open(args)
    try:
        for k, v in m.grbl_settings().items():      # make sure the board agrees
            g.set_setting(k, v)
        print("Referenzfahrt ...")
        mpos = hm.reference(g, m.homing)
        m.save(Path(args.machine))
        print("Maschinenposition am Schalter:", "  ".join(f"{a}{mpos[a]:.3f}" for a in AXES))
        st = g.status()
        print("Arbeitsposition jetzt:       ", "  ".join(f"{a}{st['mpos'][a] - m.homing.work_origin(mpos)[a]:.3f}" for a in AXES))
        return 0
    except (GrblError, GrblAlarm, TimeoutError, RuntimeError) as e:
        print(f"Referenzfahrt fehlgeschlagen: {e}", file=sys.stderr)
        return 1
    finally:
        g.link.close()


def _parse_axis_values(items) -> dict[str, float]:
    out = {}
    for item in items or []:
        axis, _, val = item.partition("=")
        axis = axis.strip().upper()
        if axis not in AXES:
            raise ValueError(f"Achse muss X, Y, U oder V sein: {item!r}")
        out[axis] = float(val.replace(",", "."))
    return out


def cmd_homing(args) -> int:
    """Show or edit the limit switch configuration (no hardware needed)."""
    path = Path(args.machine)
    m = Machine.load_or_none(path) or Machine()
    h = m.homing
    if args.homing_action == "set":
        try:
            offsets = _parse_axis_values(args.offset)
            lengths = _parse_axis_values(args.length)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if args.enable:
            h.enabled = True
        if args.disable:
            h.enabled = False
        if args.nc:
            h.invert_switch = True
        if args.no:
            h.invert_switch = False
        if args.pulloff is not None:
            h.pulloff = args.pulloff
        if args.no_soft_limits:
            h.soft_limits = False
        h.offset_mm.update(offsets)
        h.length_mm.update(lengths)
        if h.enabled and not all(h.length_mm[a] > 0 for a in AXES):
            print("warnung: nicht alle Laengen gesetzt (--length X=.. Y=.. U=.. V=..)", file=sys.stderr)
        m.save(path)
        print(f"gespeichert: {path}")
    print(f"Endschalter: {'AN' if h.enabled else 'aus'}   Schalter: {'Oeffner (NC)' if h.invert_switch else 'Schliesser (NO)'}"
          f"   Pull-off {h.pulloff:g} mm   Softlimits {'an' if h.soft_limits else 'aus'}")
    print("  Achse  Laenge ab Schalter  Versatz +  nutzbar")
    for a in AXES:
        print(f"    {a}    {h.length_mm[a]:10.1f} mm   {h.offset_mm[a]:7.2f}   {h.usable_travel(a):7.1f} mm")
    if h.home_mpos:
        print("  letzte Referenzfahrt, MPos:", "  ".join(f"{a}{h.home_mpos[a]:.3f}" for a in AXES))
    return 0


def cmd_machine(args) -> int:
    """Show or set machine-level numbers that no wizard measures."""
    path = Path(args.machine)
    m = Machine.load_or_none(path) or Machine()
    if args.machine_action == "set":
        if args.tower_gap is not None:
            if args.tower_gap <= 0:
                print("error: tower gap muss > 0 sein", file=sys.stderr)
                return 2
            m.tower_gap_mm = args.tower_gap
            m.tower_gap_measured = True
        if args.wire_fixed is not None:
            m.wire_fixed_tower = args.wire_fixed
        if args.feed is not None:
            m.cut_feed = args.feed
        if args.wire is not None:
            m.wire_power = args.wire
        if args.warmup is not None:
            m.warmup_s = args.warmup
        if args.kerf is not None:
            if args.kerf < 0:
                print("error: kerf muss >= 0 sein", file=sys.stderr)
                return 2
            m.kerf_mm = args.kerf
        m.save(path)
        print(f"gespeichert: {path}")
    print(f"Turmabstand (Drahtaufhaengungen): {m.tower_gap_mm:g} mm"
          + ("" if m.tower_gap_measured else "   <- NICHT gemessen, Platzhalter"))
    print(f"Draht fest an Turm {m.wire_fixed_tower} ({'X/Y' if m.wire_fixed_tower == 1 else 'U/V'}), "
          "dort liegt die Fluegelwurzel")
    print(f"Schnitt: Vorschub {m.cut_feed:g} mm/min, Draht S{m.wire_power} (0 = GUI-Schieber), "
          f"Aufheizen {m.warmup_s:g} s, Schnittbreite (Kerf) {m.kerf_mm:g} mm")
    print("Schritte/mm:", "  ".join(f"{a} {m.steps_per_mm[a]:g}" for a in AXES))
    print("Max mm/min: ", "  ".join(f"{a} {m.max_rate[a]:g}" for a in AXES))
    print("Verfahrweg: ", "  ".join(f"{a} {m.travel_mm[a]:g}" for a in AXES))
    return 0


def cmd_jogpad(args) -> int:
    """Keyboard jogging, nothing else."""
    g, w = _wizard(args)
    try:
        w._prepare()
        pos = w.jogpad("Freies Verfahren. Enter beendet.")
        print("Position:", "  ".join(f"{a}{v:.3f}" for a, v in pos.items()))
        return 0
    except wiz.Abort as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    finally:
        g.link.close()


def cmd_wing(args) -> int:
    """Generate one-pass XYUV G-code for a wing panel from a .wing spec."""
    from .wing import WING_MODEL
    return _cmd_design(args, WING_MODEL, "wing")


def cmd_shape(args) -> int:
    """Generate one-pass XYUV G-code for a free shape (disc or ring) from a .shape spec."""
    from .shape import SHAPE_MODEL
    return _cmd_design(args, SHAPE_MODEL, "shape")


def cmd_contour(args) -> int:
    """Generate a prismatic (X=U, Y=V) program for the outlines of an SVG from a .contour spec."""
    from .contour import CONTOUR_MODEL
    return _cmd_design(args, CONTOUR_MODEL, "contour")


def cmd_slices(args) -> int:
    """Generate the program for one slab of an STL body from a .slices spec."""
    from .slices import SLICE_MODEL
    return _cmd_design(args, SLICE_MODEL, "slices")


def cmd_esp(args) -> int:
    """Programs on an ESP32/ESP3D in front of the board: list, upload, start, watch."""
    from .esp import Esp3d, EspError
    e = Esp3d(args.host)
    try:
        if args.esp_action == "ls":
            jobs = e.jobs()
            if not jobs:
                print("keine Programme im ESP-Flash")
            for j in jobs:
                print(f"{j.name:32s} Block {j.block or '?':>12s}  X={j.x or '?':>4s} Tisch Y={j.y or '?':>4s}  "
                      f"Wurzel {j.root or '?'}  {j.time or '?'}  {j.title}")
        elif args.esp_action == "put":
            for f in args.files:
                print(e.upload(Path(f)).strip() or f"hochgeladen: {f}")
        elif args.esp_action == "start":
            print(e.start(args.files[0]).strip())
        elif args.esp_action in ("pause", "resume", "abort"):
            print(e.stream(args.esp_action))
        else:
            st = e.stream()
            print(st)
    except EspError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except IndexError:
        print("error: Dateiname fehlt", file=sys.stderr)
        return 2
    return 0


def cmd_nest(args) -> int:
    """Several parts in one block from a .batch list -> one program."""
    from . import nest as ns
    from .wing import WingError
    if args.template:
        sys.stdout.write(ns.Batch(items=[ns.Item("mein.wing", True), ns.Item("rumpf.shape")]).to_text())
        return 0
    if not args.batch:
        print("foamcut nest LISTE.batch -o OUT.nc   oder   foamcut nest --template > liste.batch", file=sys.stderr)
        return 2
    m = Machine.load_or_none(Path(args.machine)) or Machine()
    try:
        batch = ns.Batch.parse(Path(args.batch).read_text(), Path(args.batch).parent)
        code, nest = ns.generate(batch, m, Path(args.airfoils))
    except (WingError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for n in nest.notes:
        print(f"  {n}")
    ext = nest.extents()
    print("  Schlittenweg: " + "  ".join(f"{a} {lo:.1f}..{hi:.1f}" for a, (lo, hi) in ext.items()))
    problems = m.check_extents(ext) if m.has_travel() else []
    for pr in problems:
        print(f"  VERFAHRWEG: {pr}")
    prog = gc.Program.parse(code)
    for e in prog.errors:
        print(f"  ERROR: {e}")
    out = Path(args.out) if args.out else Path(args.batch).with_suffix(".nc")
    out.write_text(code)
    print(f"geschrieben: {out}")
    return 1 if (problems or prog.errors) else 0


def _cmd_design(args, model, cmd: str) -> int:
    from .wing import WingError
    if args.template:
        sys.stdout.write(model.template)
        return 0
    if not args.spec:
        print(f"foamcut {cmd} SPEC.{cmd} -o OUT.nc   oder   foamcut {cmd} --template > mein.{cmd}", file=sys.stderr)
        return 2
    m = Machine.load_or_none(Path(args.machine)) or Machine()
    try:
        spec = model.parse(Path(args.spec).read_text())
        code, path = model.generate(spec, m, Path(args.airfoils))
    except (WingError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for n in path.notes:
        print(f"  {n}")
    ext = path.extents()
    print("  Schlittenweg: " + "  ".join(f"{a} {lo:.1f}..{hi:.1f}" for a, (lo, hi) in ext.items()))
    problems = m.check_extents(ext) if m.has_travel() else []
    for pr in problems:
        print(f"  VERFAHRWEG: {pr}")
    prog = gc.Program.parse(code)
    for e in prog.errors:
        print(f"  ERROR: {e}")
    out = Path(args.out) if args.out else Path(args.spec).with_suffix(".nc")
    out.write_text(code)
    print(f"geschrieben: {out}")
    return 1 if (problems or prog.errors) else 0


def cmd_sim(args) -> int:
    """Simulate a program: both carriage paths drawn turtle-style, no hardware."""
    import tkinter as tk
    from .gui_sim import open_sim_window
    text, prog = _load_program(args)
    m = Machine.load_or_none(Path(args.machine)) or Machine()
    root = tk.Tk()
    root.withdraw()
    win = open_sim_window(root, text.splitlines(), m, Path(args.file).name)
    win.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return 0


def cmd_gui(args) -> int:
    """The graphical interface: Qt by default, the older Tk one with --tk."""
    if args.tk:
        from .gui import run_gui
        return run_gui(args.port, args.baud, Path(args.machine))
    try:
        from .qt.mainwindow import run
    except ImportError as e:
        print(f"PyQt6 fehlt ({e}); starte die Tk-Oberflaeche. pip install PyQt6", file=sys.stderr)
        from .gui import run_gui
        return run_gui(args.port, args.baud, Path(args.machine))
    return run(args.port, args.baud, Path(args.machine))


def cmd_console(args) -> int:
    g = _open(args)
    print("connected. Type a command, or 'quit'. Ctrl-C sends a soft reset.")
    try:
        while True:
            try:
                line = input("fc> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                g.link.write_raw(b"\x18")
                break
            if not line:
                continue
            if line in ("quit", "exit"):
                break
            if line == "?":
                print(g.status()["raw"])
                continue
            try:
                for resp in g.command(line):
                    print(f"< {resp}")
                print("< ok")
            except (GrblError, GrblAlarm, TimeoutError) as e:
                print(f"! {e}", file=sys.stderr)
    finally:
        g.link.close()
    return 0


def cmd_hwtest(args) -> int:
    """Guided wiring check against the hwtest firmware (not grbl)."""
    link = open_link(args.port, args.baud)
    try:
        return hwt.run(link, auto=args.auto, revs=args.revs, step_us=args.step_us)
    except hwt.HwtestError as e:
        print(f"\nabgebrochen: {e}", file=sys.stderr)
        try:
            link.write_line("en 0")   # never leave the motors energised
        except Exception:
            pass
        return 1
    finally:
        link.close()


def cmd_bounce(args) -> int:
    """Move axes back and forth on the hwtest firmware. No endstops needed."""
    axes = AXES if args.axis.lower() == "all" else (args.axis.upper(),)
    for a in axes:
        if a not in AXES:
            print(f"axis must be one of {', '.join(AXES)} or 'all'", file=sys.stderr)
            return 2
    if not 1 <= args.step_us <= 65535:
        print("--step-us muss zwischen 40 und 65535 liegen "
              "(die Firmware haelt stepUs in einem uint16_t)", file=sys.stderr)
        return 2
    steps = args.steps if args.steps else round(args.mm * args.spmm)
    print(f"{args.mm:g} mm bei {args.spmm:g} Schritten/mm = {steps} Schritte je Richtung")
    if not args.steps:
        print("(--spmm anpassen, wenn deine Spindel anders ist; nachmessen und")
        print(" neu rechnen: spmm_neu = spmm_alt * befohlen / gemessen)")
    link = open_link(args.port, args.baud)
    try:
        return hwt.bounce(link, axes, steps, args.step_us, guard=not args.no_guard)
    except hwt.HwtestError as e:
        print(f"\nabgebrochen: {e}", file=sys.stderr)
        try:
            link.write_line("en 0")
        except Exception:
            pass
        return 1
    finally:
        link.close()


def cmd_selftest(args) -> int:
    """Drive each axis out and back through grbl and check it came home."""
    g = _open(args)
    try:
        st = g.status()
        if st["state"] == "Alarm":
            print("machine is in Alarm, unlocking with $X")
            g.unlock()
        g.command("G21")
        g.command("G90")
        g.zero_here()
        ok = True
        for axis in AXES:
            print(f"--- {axis} ---")
            g.command(f"$J=G91 G21 {axis}{args.distance:g} F{args.feed:g}")
            g.wait_idle(timeout=120)
            out = g.status()["mpos"][axis]
            g.command(f"$J=G91 G21 {axis}{-args.distance:g} F{args.feed:g}")
            g.wait_idle(timeout=120)
            back = g.status()["mpos"][axis]
            moved = abs(out - back)
            good = abs(moved - args.distance) < 0.01 and abs(back) < 0.01
            ok &= good
            print(f"  out {out:8.3f}  back {back:8.3f}  travelled {moved:.3f} mm"
                  f"  {'OK' if good else 'MISMATCH'}")
        print("\nselftest", "passed" if ok else "FAILED")
        return 0 if ok else 1
    except (GrblError, GrblAlarm, TimeoutError) as e:
        print(f"selftest aborted: {e}", file=sys.stderr)
        return 1
    finally:
        g.link.close()


# ------------------------------------------------------------------- main ---
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="foamcut", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"foamcut {__version__}")
    p.add_argument("--port", default=DEFAULT_PORT,
                   help="serial port, 'auto' for the newest one (default), or tcp://host[:port] for an ESP3D/WiFi bridge")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--machine", default=str(MACHINE_PATH),
                   help=f"machine description (default {MACHINE_PATH})")
    sub = p.add_subparsers(dest="cmd", required=True)

    fmt_help = "axis letters of the file: auto, XYUV, XYAZ (hotwireairfoil), XYZA"

    c = sub.add_parser("check", help="validate a G-code file offline")
    c.add_argument("file")
    c.add_argument("--format", default="auto", choices=["auto", *gc.AXIS_PRESETS], help=fmt_help)
    c.set_defaults(func=cmd_check)

    c = sub.add_parser("convert", help="translate a generator's file to grbl XYUV")
    c.add_argument("file")
    c.add_argument("out")
    c.add_argument("--format", default="auto", choices=["auto", *gc.AXIS_PRESETS], help=fmt_help)
    c.add_argument("--wire", type=int, help="replace relay-style M3 S1 with this PWM 1..255")
    c.set_defaults(func=cmd_convert)

    c = sub.add_parser("gen", help="generate a test G-code file")
    c.add_argument("what", choices=["square", "taper", "bounce"])
    c.add_argument("--axis", default="X", help="for 'bounce'")
    c.add_argument("--size", type=float, default=50.0)
    c.add_argument("--feed", type=float, default=300.0)
    c.add_argument("-o", "--out")
    c.set_defaults(func=cmd_gen)

    c = sub.add_parser("probe", help="what is on the serial port?")
    c.set_defaults(func=cmd_probe)

    c = sub.add_parser("status", help="one status report")
    c.set_defaults(func=cmd_status)

    c = sub.add_parser("pins", help="watch the limit switch inputs (Pn field) to map switches to axes")
    c.add_argument("--seconds", type=float, default=90.0)
    c.set_defaults(func=cmd_pins)

    c = sub.add_parser("settings", help="read or write grbl $ settings")
    c.add_argument("settings_action", choices=["dump", "apply"])
    c.add_argument("file", nargs="?")
    c.set_defaults(func=cmd_settings)

    c = sub.add_parser("jog", help="jog one axis")
    c.add_argument("axis")
    c.add_argument("distance", type=float)
    c.add_argument("--feed", type=float, default=300.0)
    c.set_defaults(func=cmd_jog)

    c = sub.add_parser("wire", help="set hot wire power 0..255")
    c.add_argument("power", type=int)
    c.set_defaults(func=cmd_wire)

    c = sub.add_parser("run", help="stream a G-code file")
    c.add_argument("file")
    c.add_argument("--format", default="auto", choices=["auto", *gc.AXIS_PRESETS], help=fmt_help)
    c.add_argument("--wire", type=int, help="replace relay-style M3 S1 with this PWM 1..255")
    c.add_argument("--force", action="store_true")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(func=cmd_run)

    c = sub.add_parser("hwtest", help="[nur Erst-Inbetriebnahme, braucht hwtest-Firmware] guided wiring check")
    c.add_argument("--auto", action="store_true", help="do not ask, just run")
    c.add_argument("--revs", type=float, default=1.0, help="motor turns per axis")
    c.add_argument("--step-us", type=int, default=400, dest="step_us")
    c.set_defaults(func=cmd_hwtest)

    c = sub.add_parser("bounce", help="[nur Erst-Inbetriebnahme, braucht hwtest-Firmware] move axes out and back")
    c.add_argument("axis", nargs="?", default="all", help="X, Y, U, V or all")
    c.add_argument("--mm", type=float, default=20.0, help="travel per direction")
    c.add_argument("--spmm", type=float, default=400.0,
                   help="steps per mm (400 = 1/16 microstep, T8 lead screw)")
    c.add_argument("--steps", type=int, help="step count, overrides --mm/--spmm")
    c.add_argument("--step-us", type=int, default=250, dest="step_us")
    c.add_argument("--no-guard", action="store_true",
                   help="do not stop on an endstop (none wired)")
    c.set_defaults(func=cmd_bounce)

    c = sub.add_parser("setup", help="measure the machine (grbl): mapping, scale, direction, reference, travel")
    c.add_argument("--phases", nargs="+", default=["mapping", "scale", "direction", "reference", "travel"],
                   choices=["mapping", "scale", "direction", "reference", "travel"])
    c.add_argument("--jog-mm", type=float, default=20.0, dest="jog_mm",
                   help="Teststrecke fuer mapping/scale/direction (default 20)")
    c.add_argument("--axes", nargs="+", metavar="AXIS",
                   help="nur diese Achsen in scale/direction/travel, z.B. --axes U")
    c.add_argument("--spmm", type=float,
                   help="Startwert Schritte/mm fuer alle Achsen, z.B. 2560 bei M8 1,25 mm")
    c.set_defaults(func=cmd_setup)

    c = sub.add_parser("ref", help="manual referencing: jog to the corner, set zero")
    c.set_defaults(func=cmd_ref)

    c = sub.add_parser("home", help="homing on the switches + work origin from the offsets")
    c.set_defaults(func=cmd_home)

    c = sub.add_parser("homing", help="show / edit the limit switch configuration")
    c.add_argument("homing_action", choices=["show", "set"])
    c.add_argument("--enable", action="store_true")
    c.add_argument("--disable", action="store_true")
    c.add_argument("--nc", action="store_true", help="switches are normally closed")
    c.add_argument("--no", action="store_true", help="switches are normally open (default)")
    c.add_argument("--pulloff", type=float)
    c.add_argument("--no-soft-limits", action="store_true", dest="no_soft_limits")
    c.add_argument("--offset", nargs="*", metavar="AXIS=MM", help="work origin offset from the switch, e.g. V=1.5")
    c.add_argument("--length", nargs="*", metavar="AXIS=MM", help="usable length from the switch, e.g. X=160")
    c.set_defaults(func=cmd_homing)

    c = sub.add_parser("machine", help="show / set tower gap and the measured numbers")
    c.add_argument("machine_action", choices=["show", "set"])
    c.add_argument("--tower-gap", type=float, dest="tower_gap",
                   help="Abstand der beiden Drahtaufhaengungen in mm (messen!)")
    c.add_argument("--wire-fixed", type=int, choices=(1, 2), dest="wire_fixed",
                   help="Turm, an dem der Draht fest eingespannt ist (1 = X/Y, 2 = U/V); Wurzelseite")
    c.add_argument("--kerf", type=float, help="Schnittbreite in mm (Testschnitt messen); gilt fuer Fluegel, Formen, Stapel")
    c.add_argument("--feed", type=float, help="Drahtvorschub mm/min (schnellere Schnittebene)")
    c.add_argument("--wire", type=int, help="Heizleistung S 1..255, 0 = GUI-Schieber")
    c.add_argument("--warmup", type=float, help="Aufheizzeit in s vor der ersten Fahrt")
    c.set_defaults(func=cmd_machine)

    c = sub.add_parser("jogpad", help="keyboard jogging")
    c.set_defaults(func=cmd_jogpad)

    c = sub.add_parser("wing", help="wing panel -> one-pass XYUV G-code")
    c.add_argument("spec", nargs="?", help=".wing text file (foamcut wing --template)")
    c.add_argument("-o", "--out")
    c.add_argument("--airfoils", default="airfoil", help="directory with .dat files")
    c.add_argument("--template", action="store_true", help="print a spec template")
    c.set_defaults(func=cmd_wing)

    c = sub.add_parser("shape", help="free shape (disc/ring, one cross-section per side) -> one-pass G-code")
    c.add_argument("spec", nargs="?", help=".shape text file (foamcut shape --template)")
    c.add_argument("-o", "--out")
    c.add_argument("--airfoils", default="airfoil", help=argparse.SUPPRESS)
    c.add_argument("--template", action="store_true", help="print a spec template")
    c.set_defaults(func=cmd_shape)

    c = sub.add_parser("contour", help="SVG outlines (letters, silhouettes) -> prismatic one-pass G-code")
    c.add_argument("spec", nargs="?", help=".contour text file (foamcut contour --template)")
    c.add_argument("-o", "--out")
    c.add_argument("--airfoils", default="airfoil", help=argparse.SUPPRESS)
    c.add_argument("--template", action="store_true", help="print a spec template")
    c.set_defaults(func=cmd_contour)

    c = sub.add_parser("slices", help="one slab of an STL body (lofted between its two sections) -> G-code")
    c.add_argument("spec", nargs="?", help=".slices text file (foamcut slices --template)")
    c.add_argument("-o", "--out")
    c.add_argument("--airfoils", default="airfoil", help=argparse.SUPPRESS)
    c.add_argument("--template", action="store_true", help="print a spec template")
    c.set_defaults(func=cmd_slices)

    c = sub.add_parser("esp", help="programs on an ESP32 running ESP3D: ls | put FILE.. | start NAME | status | pause | resume | abort")
    c.add_argument("esp_action", choices=["ls", "put", "start", "status", "pause", "resume", "abort"])
    c.add_argument("files", nargs="*", help="files to upload, or the program name to start")
    c.add_argument("--host", default="foamcut.local", help="ESP3D host name or IP (default foamcut.local)")
    c.set_defaults(func=cmd_esp)

    c = sub.add_parser("nest", help="several saved parts stacked in one block -> one program")
    c.add_argument("batch", nargs="?", help=".batch list (foamcut nest --template)")
    c.add_argument("-o", "--out")
    c.add_argument("--airfoils", default="airfoil", help=argparse.SUPPRESS)
    c.add_argument("--template", action="store_true")
    c.set_defaults(func=cmd_nest)

    c = sub.add_parser("sim", help="draw both carriage paths of a program, turtle-style")
    c.add_argument("file")
    c.add_argument("--format", default="auto", choices=["auto", *gc.AXIS_PRESETS], help=fmt_help)
    c.set_defaults(func=cmd_sim)

    c = sub.add_parser("gui", help="graphical interface (Qt; --tk for the old one)")
    c.add_argument("--tk", action="store_true", help="use the tkinter interface")
    c.set_defaults(func=cmd_gui)

    c = sub.add_parser("console", help="interactive command console")
    c.set_defaults(func=cmd_console)

    c = sub.add_parser("selftest", help="move every axis out and back, verify position")
    c.add_argument("--distance", type=float, default=10.0)
    c.add_argument("--feed", type=float, default=300.0)
    c.set_defaults(func=cmd_selftest)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "settings" and args.settings_action == "apply" and not args.file:
        print("settings apply needs a file", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except LinkError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
