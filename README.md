# foamcut — GT2560 XYUV hot wire cutter, bring-up project

A test bootstrap for a 4 axis hot wire foam cutter running on a Geeetech
GT2560. Two independent towers, four axes: **X/Y** on the left tower, **U/V**
on the right. Firmware is [grbl-Mega-5X](https://github.com/fra589/grbl-Mega-5X)
with a GT2560 pin map written for this project.

Nothing here needs the machine to exist yet — `make test` runs 77 checks
offline, including a cross-check that the two firmwares' pin maps describe the
same physical board.

```
make deps && make test          # offline
make grbl-flash                 # the one firmware, docs/bringup.md step 3
foamcut settings apply config/grbl_settings_foamcut.txt
foamcut setup                        # step 4: measure, no limit switches needed
foamcut run gcode/02_taper.nc
```

Follow **[docs/bringup.md](docs/bringup.md)** in order. It is written so that a
failure at any step can only have been caused by that step.

## Why not the obvious options

**Not RAMPS.** The GT2560 is a Mega 2560 with the driver sockets and MOSFETs on
the same PCB, but it is *not* RAMPS pin compatible. `motor_test/motor_test.ino`
in this directory is an example of the failure mode: it drives RAMPS pin
numbers (D54/D55/D38 for X) on a board whose X driver is on D25/D23/D27, so
nothing moves and nothing reports an error. The correct plain-Arduino sketch
is [`gt2560_motortest/`](gt2560_motortest/). See
[docs/gt2560_pinout.md](docs/gt2560_pinout.md).

**Not Marlin.** Marlin plans one E axis per move, so `X Y Z E` gives you four
simultaneous axes only if you accept that the fourth is an extruder with
extruder semantics — `M92`/`T0`/`M83`, no `U`/`V` letters, no `G28` per tower,
and no G-code generator that emits it. The `Marlin/` tree here is configured
that way (`EXTRUDERS 2`, `BOARD_GT2560_REV_A_PLUS`) and is kept as a reference,
but a foam cutter wants XYUV, not XYZE.

**Not the reference repo's firmware.** [rahulsarchive/4AxisFoamCutter](https://github.com/rahulsarchive/4AxisFoamCutter)
is a good build log and its notes on wire temperature, feed rate and G-code
generators are worth reading. It contains no firmware source, though — it
points at a grbl 0.8c2 fork for Mega/RAMPS. grbl-Mega-5X is the maintained
descendant of that idea, handles up to 6 axes, and lets the axis letters be
renamed, which is how this build gets real `U` and `V` words.

## Layout

| path | what |
|---|---|
| `firmware/hwtest/` | Bring-up fallback only: bit-bangs pins without a planner, for a board that shows no sign of life. Normal operation runs grbl exclusively. |
| `gt2560_motortest/` | Plain Arduino `.ino` with the correct GT2560 pins: pick X/Y/Z/U on the console, set microstepping, bounce motors. No PlatformIO needed. |
| `firmware/grbl5x/` | `build.sh` fetches grbl-Mega-5X, `configure.py` applies the XYUV/GT2560 overlay, then it builds and flashes. Every patch is anchored and verified, so an upstream change fails loudly instead of producing a firmware with a wrong pin map. |
| `firmware/grbl5x/overlay/cpu_map_gt2560.h` | the GT2560 pin map for grbl |
| `config/grbl_settings_foamcut.txt` | `$` settings, commented, with `MACHINE` marking every value you must measure |
| `host/` | the `foamcut` command line tool and its tests |
| `host/foamcut/qt/` | the PyQt6 interface; the masks are Qt Designer files in `qt/ui/*.ui` (loaded with `uic.loadUi`), dynamic widgets such as the mm canvases go into named placeholder layouts/splitters; `config/ui_state.json` remembers the last wing values, program and page |
| `gcode/` | test programs, from a single axis bounce to a tapered block |
| `airfoil/` | 295 airfoil `.dat` files (UIUC database via swarfer.co.za) |
| `config/beispiel.wing` | wing spec template, matches the measured travel |
| `config/beispiel.shape` | free-shape spec template (fuselage segment, ring) |
| `config/beispiel.contour`, `beispiel.svg` | SVG outline spec: ring, triangle and an "A" with its hole |
| `config/beispiel.slices`, `beispiel.stl` | slab spec: a 200 mm fuselage body in 40 mm slices |
| `docs/` | pinout and bring-up checklist |

## The `foamcut` tool

Two ways to run it, both identical:

```bash
./foamcut probe                      # wrapper in the checkout, no install needed
pip install --user -e host      # once; then plain `foamcut probe` from anywhere
```

```
foamcut check FILE          validate G-code offline: unsupported codes, missing
                       feeds, Z words on an XYUV machine, extents, run time,
                       and travel against config/machine.json
foamcut setup               measure the machine: axis mapping, steps/mm, direction,
                       manual reference, travel  -> config/machine.json
foamcut ref                 manual referencing after every power-up (no switches)
foamcut home                homing on the switches, work origin = switch + offset
foamcut homing show|set     limit switch config: NO/NC, pull-off, per-axis offset
                       and length (typed, not driven); saved in machine.json
foamcut jogpad              keyboard jogging
foamcut gui                 mouse jog pad, reference/travel buttons, hot wire,
                       load + play a G-code file with pause/stop
foamcut sim FILE       both carriage paths drawn turtle-style, no hardware
                       (also in the GUI: "Simulation" next to Start)
foamcut wing SPEC.wing      wing panel: root/tip airfoil + chords, panel length,
                       sweep, washout, mirror -> one-pass XYUV G-code
                       (root always at the fixed-wire tower, `machine set --wire-fixed`;
                       block face and table top are the anchors, lead-in runs
                       inside the foam, margins give the minimal block, the
                       tool reports the allowed table height range and extent;
                       chords from area + taper; optional aileron hinge cut)
                       (GUI "Flügel…": form with validated fields, live preview,
                       stale-program warning; foamcut wing --template for the text form)
foamcut shape SPEC.shape    free shape in one pass: rounded rectangle / triangle /
                       circle / ellipse on each side, disc or ring (slit at the
                       rear), same placement as wings (GUI page "Formen";
                       foamcut shape --template)
foamcut contour SPEC.contour  outlines of an SVG (letters, silhouettes, sketches from
                       Inkscape) cut prismatically, X=U / Y=V: kerf, slits to holes,
                       several pieces routed around each other (GUI page "Kontur";
                       foamcut contour --template)
foamcut slices SPEC.slices  one slab of an STL body: side A = section at the slab's
                       start, side B at its end, lofted (smooth stack instead of
                       steps); or prismatic through the middle. Fuselages, big
                       wings from foam slices on spars (GUI page "Scheiben")
foamcut nest LIST.batch     several saved parts stacked in one block, one program
                       (GUI page "Schachteln"; pairs: mirror-image panel nested
                       thin-over-thick; wire travels behind the block face)
foamcut gen square|taper|bounce
foamcut selftest            move every axis out and back, verify it came home
foamcut settings dump|apply
foamcut jog AXIS DIST
foamcut wire 0..255
foamcut run FILE            stream, stopping on the exact line that failed
foamcut console
```

`check` and `gen` need no hardware. `check`, `run` and the GUI translate
generator output on the fly (`foamcut convert` writes the result to a file):

| generator | axis letters | handled |
|---|---|---|
| hotwireairfoil.coolpixx.de | `X Y A Z` (A horizontal, Z vertical) | A→U, Z→V, `G64` dropped, `F` added after `G94`, `M3 S1` → real wire power |
| Jedicut, WingGcode | `X Y U V` | unsupported header codes reported |
| LinuxCNC style | `X Y Z A` | `--format XYZA` |

`G93` inverse time feed is passed through — grbl supports it.

## Two things that will bite you

**The bed MOSFET cannot drive the wire under grbl.** D4 is on timer 0, which
grbl uses for the step pulse reset interrupt. The wire PWM is on D3 (timer 3)
instead — a hotend-sized MOSFET, about 40 W. For a metre of nichrome, use D3 to
gate an external MOSFET and keep the current off the board.

**The feed rate is a four axis vector.** With `N_AXIS_LINEAR = 4`, `F300` on a
move where both towers travel 100 mm gives each tower 212 mm/min, not 300.
`foamcut check` flags this per file.

## Licence

`firmware/grbl5x/overlay/` and `configure.py` derive from grbl-Mega-5X and are
GPLv3. The rest is yours to do as you like with.

## Erster Testlauf

```bash
make hwtest-flash     # Selbsttest-Firmware aufs Board
foamcut probe              # welcher Port, welche Firmware antwortet
foamcut hwtest             # gefuehrter Durchlauf, Pruefprotokoll am Ende
```

`foamcut hwtest` fragt nach jeder Achse nach, ob sie sich bewegt hat — die Firmware
kann Schritte zaehlen, aber nicht sehen, ob sich die Welle gedreht hat. Bei
"nein" grenzt er die Ursache ein: Spulenpaare vertauscht, Treiber verkehrt
herum, Vref auf null, oder STEP-Signal fehlt.
