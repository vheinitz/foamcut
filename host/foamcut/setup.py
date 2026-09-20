"""foamcut setup - measure and reference a machine that has no limit switches.

Phases, each of which can also be run on its own:

  mapping     which physical motion each grbl axis produces; refuses to go on
              if the motors are not plugged into the slots the firmware expects
  scale       steps per mm, by moving a known distance and measuring it
  direction   which way is positive; fixes $3 instead of rewiring
  reference   jog all four axes to the reference corner by hand and set zero
  travel      jog each axis to its far end, record the usable travel

Everything measured lands in config/machine.json and in grbl's settings.
The console is abstracted (Console / ScriptedConsole) so the whole wizard is
testable against a FakeLink without a keyboard.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from . import AXES
from .grbl import Grbl, GrblAlarm, GrblError
from .machine import Machine, rate_cap

MOTIONS = [
    "linker Turm, waagerecht  (X)",
    "linker Turm, senkrecht   (Y)",
    "rechter Turm, waagerecht (U)",
    "rechter Turm, senkrecht  (V)",
    "nichts hat sich bewegt",
]
REPEAT = "nochmal fahren"
DIRECTION_ANSWERS = ["ja, richtig herum", "nein, falsch herum", REPEAT]
SLOT_OF = {"X": "X", "Y": "Y", "U": "Z", "V": "E0"}
POSITIVE = {
    "X": "nach vorne (vom Nullpunkt hinten weg)",
    "Y": "nach oben",
    "U": "nach vorne (vom Nullpunkt hinten weg)",
    "V": "nach oben",
}
JOG_KEYS = {
    "a": ("X", -1), "d": ("X", +1), "s": ("Y", -1), "w": ("Y", +1),
    "j": ("U", -1), "l": ("U", +1), "k": ("V", -1), "i": ("V", +1),
}
STEP_KEYS = {"1": 0.1, "2": 1.0, "3": 10.0, "4": 50.0}


class Abort(RuntimeError):
    pass


# ------------------------------------------------------------- consoles -----
class Console:
    """Real terminal."""

    def say(self, text: str = "") -> None:
        print(text, flush=True)

    def ask(self, prompt: str) -> str:
        try:
            return input(f"  {prompt} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise Abort("abgebrochen") from None

    def ready(self, what: str) -> None:
        """Announce a move and wait for Enter before making it."""
        a = self.ask(f">> {what}   [Enter = fahren, q = Abbruch]").lower()
        if a == "q":
            raise Abort("abgebrochen")

    def yes(self, prompt: str) -> bool:
        while True:
            a = self.ask(f"{prompt} [j/n]").lower()
            if a in ("j", "ja", "y", "yes"):
                return True
            if a in ("n", "nein", "no"):
                return False

    def number(self, prompt: str, default: float | None = None) -> float:
        while True:
            raw = self.ask(f"{prompt}" + (f" [{default:g}]" if default is not None else ""))
            if not raw and default is not None:
                return default
            try:
                return float(raw.replace(",", "."))
            except ValueError:
                self.say("  bitte eine Zahl")

    def choose(self, prompt: str, options: list[str]) -> int:
        self.say(f"  {prompt}")
        for i, o in enumerate(options, start=1):
            self.say(f"    {i}) {o}")
        while True:
            raw = self.ask("Nummer:")
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return int(raw) - 1

    def key(self) -> str:
        """One keypress, no enter needed."""
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if ch in ("\x03", "\x04"):
            raise Abort("abgebrochen")
        return ch


class ScriptedConsole(Console):
    """Answers from a list, for tests. Records everything said."""

    def __init__(self, answers: list):
        self.answers = list(answers)
        self.log: list[str] = []

    def say(self, text: str = "") -> None:
        self.log.append(text)

    def _next(self, kind: str):
        if not self.answers:
            raise Abort(f"script ran out of answers at {kind}")
        return self.answers.pop(0)

    def ask(self, prompt: str) -> str:
        self.log.append(f"? {prompt}")
        return str(self._next("ask"))

    def ready(self, what: str) -> None:
        self.log.append(f">> {what}")

    def yes(self, prompt: str) -> bool:
        self.log.append(f"? {prompt}")
        return bool(self._next("yes"))

    def number(self, prompt: str, default: float | None = None) -> float:
        self.log.append(f"? {prompt}")
        v = self._next("number")
        return default if v is None else float(v)

    def choose(self, prompt: str, options: list[str]) -> int:
        self.log.append(f"? {prompt}")
        return int(self._next("choose"))

    def key(self) -> str:
        return str(self._next("key"))


# --------------------------------------------------------------- wizard -----
@dataclass
class Wizard:
    grbl: Grbl
    machine: Machine
    con: Console
    origin: dict[str, float] | None = None   # MPos of the reference corner
    jog_mm: float = 20.0                     # test distance for mapping/direction
    axes: tuple = AXES                       # which axes the scale/direction/travel phases touch

    # ----------------------------------------------------------- helpers ---
    def _prepare(self) -> None:
        st = self.grbl.status()
        if st["state"] == "Alarm":
            self.con.say("  grbl ist im Alarm, entsperre mit $X")
            self.grbl.unlock()
        self.grbl.command("G21")
        self.grbl.command("G90")

    def _wpos(self) -> dict[str, float]:
        mpos = self.grbl.status()["mpos"]
        if self.origin is None:
            return mpos
        return {a: mpos[a] - self.origin[a] for a in AXES}

    def _fmt(self, pos: dict[str, float]) -> str:
        return "  ".join(f"{a}{pos[a]:8.3f}" for a in AXES)

    def there_and_back(self, axis: str, mm: float) -> None:
        """One visible out-and-back move. The axis ends where it started."""
        self.grbl.jog(axis, mm, self.machine.jog_feed)
        self.grbl.jog(axis, -mm, self.machine.jog_feed)

    def jogpad(self, instruction: str, axes=AXES) -> dict[str, float]:
        """Keyboard jog until Enter. Returns the work position reached."""
        step = 1.0
        self.con.say(f"\n  {instruction}")
        self.con.say("  Tasten:  X a/d   Y s/w   U j/l   V k/i    "
                     "Schritt 1=0.1 2=1 3=10 4=50 mm    Enter=fertig  q=abbruch")
        self.con.say(f"  Schritt {step:g} mm   Position {self._fmt(self._wpos())}")
        while True:
            k = self.con.key()
            if k in ("\r", "\n"):
                return self._wpos()
            if k == "q":
                raise Abort("abgebrochen")
            if k in STEP_KEYS:
                step = STEP_KEYS[k]
                self.con.say(f"  Schritt {step:g} mm")
                continue
            if k in JOG_KEYS:
                axis, sign = JOG_KEYS[k]
                if axis not in axes:
                    continue
                self.grbl.jog(axis, sign * step, self.machine.jog_feed)
                self.con.say(f"  Position {self._fmt(self._wpos())}")

    # ------------------------------------------------------------ phases ---
    def phase_mapping(self) -> bool:
        d = self.jog_mm
        spmm = self.grbl.settings().get(100, 0)
        self.con.say("\n=== 1. Achszuordnung ===")
        self.con.say(f"  Jede grbl-Achse faehrt {d:g} mm hin und wieder zurueck.")
        self.con.say(f"  (grbl rechnet mit {spmm:g} Schritten/mm. Bewegt sich fast nichts,")
        self.con.say("   stimmt dieser Wert grob nicht - foamcut setup --spmm <Schaetzwert> neu starten.)")
        seen: dict[str, int] = {}
        for axis in AXES:
            while True:
                self.con.ready(f"Achse {axis}: +{d:g} mm und zurueck")
                self.there_and_back(axis, d)
                i = self.con.choose("Was hat sich bewegt?", MOTIONS + [REPEAT])
                if i < len(MOTIONS):
                    seen[axis] = i
                    break
        wrong = {a: i for a, i in seen.items() if i != AXES.index(a)}
        if not wrong:
            self.con.say("  Zuordnung stimmt.")
            return True
        self.con.say("\n  Zuordnung stimmt NICHT. Steckplatz-Belegung (Board-Silkscreen):")
        for a, i in seen.items():
            self.con.say(f"    Steckplatz {SLOT_OF[a]:<2} treibt: {MOTIONS[i]}")
        self.con.say("  Erwartet wird:")
        for a in AXES:
            self.con.say(f"    Steckplatz {SLOT_OF[a]:<2} = {MOTIONS[AXES.index(a)]}")
        self.con.say("  Motorstecker entsprechend umstecken (Netzteil aus!), dann foamcut setup neu starten.")
        return False

    def phase_scale(self, distance: float | None = None) -> None:
        distance = distance or self.jog_mm
        self.con.say("\n=== 2. Schritte pro mm ===")
        self.con.say(f"  Jede Achse faehrt {distance:g} mm hin und zurueck. Markiere vorher den")
        self.con.say("  Schlitten, miss den Hinweg mit Lineal oder Messschieber.")
        settings = self.grbl.settings()
        for i, axis in enumerate(AXES):
            if axis not in self.axes:
                continue
            current = settings.get(100 + i, self.machine.steps_per_mm[axis])
            while True:
                self.con.ready(f"{axis}: +{distance:g} mm Hinweg ({current:g} Schritte/mm) - Schlitten markiert?")
                self.grbl.jog(axis, distance, self.machine.jog_feed)
                measured = self.con.number(f"{axis}: gemessener Weg in mm (0 = nochmal fahren)",
                                           default=distance)
                self.con.ready(f"{axis}: Rueckweg -{distance:g} mm")
                self.grbl.jog(axis, -distance, self.machine.jog_feed)
                if measured <= 0:
                    continue
                new = round(current * distance / measured, 3)
                if abs(new - current) > 1e-6:
                    self.grbl.set_setting(100 + i, new)
                    self.con.say(f"  {axis}: {current:g} -> {new:g} Schritte/mm  (${100 + i})")
                    # the step budget is fixed; more steps per mm means less mm per minute
                    cap = rate_cap(new)
                    self.machine.max_rate[axis] = cap
                    self.grbl.set_setting(110 + i, cap)
                    self.con.say(f"  {axis}: Maximalrate -> {cap:g} mm/min  (${110 + i}, 20 kHz)")
                    current = new
                    if self.con.yes(f"{axis}: Kontrollfahrt mit dem neuen Wert?"):
                        continue
                else:
                    self.con.say(f"  {axis}: {current:g} Schritte/mm passt")
                self.machine.steps_per_mm[axis] = current
                break

    def phase_direction(self, distance: float | None = None) -> None:
        distance = distance or self.jog_mm
        self.con.say("\n=== 3. Richtung ===")
        self.con.say("  Positiv heisst: X und U nach vorne, Y und V nach oben. Null ist hinten unten.")
        self.con.say(f"  Jede Achse faehrt +{distance:g} mm und wieder zurueck.")
        mask = int(self.grbl.settings().get(3, 0))
        for i, axis in enumerate(AXES):
            if axis not in self.axes:
                continue
            while True:
                self.con.ready(f"{axis}: +{distance:g} mm und zurueck - soll {POSITIVE[axis]} gehen")
                self.there_and_back(axis, distance)
                ans = self.con.choose(f"Ging der Hinweg {POSITIVE[axis]}?", DIRECTION_ANSWERS)
                if ans == 2:
                    continue
                if ans == 1:
                    mask ^= (1 << i)
                    self.grbl.set_setting(3, mask)
                    self.con.say(f"  {axis} invertiert ($3={mask}). Kontrollfahrt ...")
                    continue          # runs again with the new setting, must now be "ja"
                self.machine.invert_dir[axis] = bool(mask & (1 << i))
                break

    def phase_reference(self) -> None:
        self.con.say("\n=== 4. Referenzpunkt ===")
        self.con.say("  Ohne Endschalter ist die Referenz eine Ecke, die du von Hand anfaehrst:")
        self.con.say("  X und U ganz hinten, Y und V ganz unten. Nicht bis zum Anschlag druecken,")
        self.con.say("  ein paar Millimeter Luft lassen.")
        self.jogpad("Alle vier Achsen in die Referenzecke fahren, dann Enter.")
        self.origin = self.grbl.status()["mpos"]
        self.grbl.zero_here()
        self.con.say(f"  Referenz gesetzt. Arbeitsnull = {self._fmt(self.origin)} (Maschinenkoordinaten)")

    def phase_travel(self) -> None:
        self.con.say("\n=== 5. Verfahrweg ===")
        if self.origin is None:
            self.con.say("  Referenz fehlt - erst Phase 4.")
            return
        for i, axis in enumerate(AXES):
            if axis not in self.axes:
                continue
            pos = self.jogpad(f"{axis} bis kurz vor das andere Ende fahren, dann Enter.", axes=(axis,))
            travel = round(pos[axis], 3)
            if travel <= 0:
                self.con.say(f"  {axis}: {travel} mm ist kein Verfahrweg, uebersprungen")
                continue
            self.machine.travel_mm[axis] = travel
            self.grbl.set_setting(130 + i, travel)
            self.con.say(f"  {axis}: Verfahrweg {travel:.3f} mm  (${130 + i})")
            self.con.ready(f"{axis}: zurueck auf 0 ({travel:.1f} mm)")
            self.grbl.jog_to({axis: 0.0}, self.machine.jog_feed)

    # --------------------------------------------------------------- run ---
    def run(self, phases=("mapping", "scale", "direction", "reference", "travel")) -> int:
        self._prepare()
        try:
            if "mapping" in phases and not self.phase_mapping():
                return 1
            if "scale" in phases:
                self.phase_scale()
            if "direction" in phases:
                self.phase_direction()
            if "reference" in phases:
                self.phase_reference()
            if "travel" in phases:
                self.phase_travel()
        except (GrblError, GrblAlarm) as e:
            self.con.say(f"\n  grbl: {e}")
            return 1
        self.con.say("\n=== Ergebnis ===")
        for a in AXES:
            self.con.say(f"  {a}: {self.machine.steps_per_mm[a]:g} Schritte/mm, "
                         f"{'invertiert' if self.machine.invert_dir[a] else 'normal'}, "
                         f"Verfahrweg {self.machine.travel_mm[a]:g} mm")
        return 0
