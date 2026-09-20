"""Guided bring-up run against the firmware/hwtest self test firmware.

The firmware can report how many step pulses it issued, but it cannot know
whether a motor actually turned - an unpowered driver, a driver in backwards
and a swapped coil pair all look identical from the MCU side. So this is a
*guided* test: it moves one thing at a time, says what should happen, and asks
you what did. The result is a wiring report you can act on.

    foamcut hwtest             guided, asks after every axis
    foamcut hwtest --auto      run everything without asking (just watch)
"""
from __future__ import annotations

import sys
import time

from . import AXES

# 200 step motor at 1/16 microstepping = 3200 steps per revolution. One full
# turn is unmistakable to look at and is only ~8 mm on a T8 lead screw, so it
# cannot crash a carriage that is not already at the very end of its travel.
STEPS_PER_REV = 3200


class HwtestError(RuntimeError):
    pass


class Hwtest:
    """Talks to the hwtest firmware: send a line, read until 'ok'."""

    def __init__(self, link):
        self.link = link
        self.banner: list[str] = []

    def connect(self, timeout: float = 5.0) -> list[str]:
        self.banner = [l for l in self.link.drain() if l]
        deadline = time.monotonic() + timeout
        while not self.banner and time.monotonic() < deadline:
            line = self.link.read_line(timeout=0.5)
            if line:
                self.banner.append(line)
        return self.banner

    def is_hwtest(self) -> bool:
        return any("foamcut hwtest" in l for l in self.banner)

    def command(self, line: str, timeout: float = 60.0) -> list[str]:
        self.link.write_line(line)
        out: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            resp = self.link.read_line(timeout=0.5)
            if resp is None:
                continue
            if resp == "ok":
                return out
            out.append(resp)
        raise HwtestError(f"no ok for {line!r} after {timeout} s")


# ------------------------------------------------------------------- helpers --
def _ask(question: str, auto: bool) -> bool:
    if auto:
        return True
    while True:
        try:
            answer = input(f"    {question} [j/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            raise HwtestError("aborted by the operator") from None
        if answer in ("j", "y", "ja", "yes"):
            return True
        if answer in ("n", "nein", "no"):
            return False


def _say(text: str = "") -> None:
    print(text, flush=True)


def parse_endstops(lines: list[str]) -> dict[str, bool]:
    """'endstops:  Xmin=0 Xmax=0  Ymin=1 ...' -> {'Xmin': False, ...}"""
    out: dict[str, bool] = {}
    for line in lines:
        if not line.startswith("endstops:"):
            continue
        for token in line.split(":", 1)[1].split():
            if "=" in token:
                name, _, value = token.partition("=")
                out[name] = value == "1"
    return out


def parse_stepped(lines: list[str]) -> int | None:
    for line in lines:
        if line.startswith("stepped "):
            parts = line.split()
            if len(parts) >= 2 and parts[-1].isdigit():
                return int(parts[-1])
    return None


# ---------------------------------------------------------------- the run ----
def run(link, auto: bool = False, revs: float = 1.0, step_us: int = 400) -> int:
    """Returns 0 if every check passed, 1 otherwise."""
    hw = Hwtest(link)
    banner = hw.connect()
    for line in banner:
        _say(f"< {line}")
    if not hw.is_hwtest():
        _say("\nDas ist nicht die hwtest-Firmware. Erst 'make hwtest-flash'.")
        return 1

    steps = int(STEPS_PER_REV * revs)
    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, note: str = "") -> None:
        results.append((name, ok, note))
        _say(f"    -> {'OK' if ok else 'FEHLER'}{'  ' + note if note else ''}")

    # -- 0 -------------------------------------------------------------------
    _say("\n=== 0. Voraussetzungen ===")
    _say("    Das Netzteil (12/24 V) muss AN sein - USB allein versorgt die")
    _say("    Treiber nicht, die Motoren stehen dann einfach still.")
    _say("    Ein Luefter muss auf das Board blasen.")
    if not _ask("Netzteil an und Luefter laeuft?", auto):
        _say("\nAbgebrochen. Netzteil einschalten und nochmal starten.")
        return 1

    # -- 1 -------------------------------------------------------------------
    _say("\n=== 1. Pinbelegung der Firmware ===")
    for line in hw.command("map"):
        _say(f"    {line}")

    # -- 2 -------------------------------------------------------------------
    _say("\n=== 2. Endschalter im Ruhezustand ===")
    state = parse_endstops(hw.command("es"))
    if not state:
        record("Endschalter lesbar", False, "keine Antwort auf 'es'")
    else:
        closed = [n for n, hit in state.items() if hit]
        _say("    " + "  ".join(f"{n}={'1' if v else '0'}" for n, v in state.items()))
        if closed:
            record("Endschalter offen", False,
                   f"{', '.join(closed)} meldet ausgeloest - Schalter als "
                   "Oeffner verdrahtet, gedrueckt, oder Kurzschluss")
        else:
            record("Endschalter offen", True, "alle Eingaenge frei")

    # -- 3 -------------------------------------------------------------------
    _say("\n=== 3. Treiber bestromen ===")
    hw.command(f"us {step_us}")
    for line in hw.command("en 1"):
        _say(f"    {line}")
    _say("    Alle vier Motoren muessen jetzt spuerbar steif sein (Welle von")
    _say("    Hand drehen - es muss rastend blockieren).")
    record("Motoren bestromt", _ask("Alle vier Motoren halten?", auto))

    # -- 4 -------------------------------------------------------------------
    _say(f"\n=== 4. Achsen einzeln, {revs:g} Umdrehung vor und zurueck ===")
    towers = {"X": "linker Turm, waagerecht", "Y": "linker Turm, senkrecht",
              "U": "rechter Turm, waagerecht", "V": "rechter Turm, senkrecht"}
    for axis in AXES:
        _say(f"\n  --- {axis}  ({towers[axis]}) ---")
        lines = hw.command(f"bounce {axis} {steps}", timeout=steps * step_us * 4e-6 + 30)
        for line in lines:
            _say(f"    {line}")
        issued = parse_stepped(lines)
        if issued is not None and issued < steps:
            record(f"{axis}: Schritte", False,
                   f"nur {issued}/{steps} - Endschalter hat abgebrochen")
            continue
        moved = _ask(f"Hat sich {axis} bewegt (hin und zurueck, gleich weit)?", auto)
        if moved:
            record(f"{axis}: Bewegung", True)
        else:
            record(f"{axis}: Bewegung", False, _diagnose(axis, auto))

    # -- 5 -------------------------------------------------------------------
    _say(f"\n=== 5. Alle vier Achsen gleichzeitig ===")
    _say("    Das ist der Punkt, an dem eine 3-Achs-Steuerung aussteigt.")
    hw.command(f"all {steps}", timeout=steps * step_us * 4e-6 + 30)
    record("4 Achsen synchron",
           _ask("Sind alle vier gleichzeitig gelaufen und gleichzeitig stehengeblieben?", auto))

    # -- 6 -------------------------------------------------------------------
    _say("\n=== 6. Endschalter von Hand ===")
    if state and not auto:
        _say("    Jeden Schalter nacheinander von Hand druecken und schauen,")
        _say("    ob genau der zugehoerige Wert auf 1 springt.")
        if _ask("Endschalter jetzt pruefen?", auto):
            _say("    (Taste im Terminal beendet die Anzeige)")
            link.write_line("mon")
            _monitor(link)
            record("Endschalter schalten",
                   _ask("Hat jeder Schalter den richtigen Eingang ausgeloest?", auto))
        else:
            _say("    uebersprungen")
    else:
        _say("    uebersprungen")

    # -- 7 -------------------------------------------------------------------
    _say("\n=== 7. Motoren freigeben ===")
    hw.command("en 0")
    _say("    Treiber stromlos. Heizdraht war waehrend des Laufs aus.")

    # -- Bericht -------------------------------------------------------------
    _say("\n" + "=" * 60)
    _say("PRUEFPROTOKOLL")
    _say("=" * 60)
    failed = 0
    for name, ok, note in results:
        mark = "OK    " if ok else "FEHLER"
        _say(f"  [{mark}] {name}{'   ' + note if note else ''}")
        failed += 0 if ok else 1
    _say("=" * 60)
    if failed:
        _say(f"{failed} von {len(results)} Pruefungen fehlgeschlagen.")
        _say("Naechster Schritt: docs/bringup.md, Abschnitt 2.")
    else:
        _say(f"Alle {len(results)} Pruefungen bestanden.")
        _say("Naechster Schritt: 'make grbl-flash', dann docs/bringup.md ab Schritt 3.")
    return 1 if failed else 0


def bounce(link, axes=AXES, steps: int = 8000, step_us: int = 250,
           guard: bool = True, pause: float = 1.0) -> int:
    """Move each axis `steps` out and back. No questions, no endstop needed.

    Returns 0 if every axis issued the full step count. A short count means the
    firmware's endstop guard stopped the move, which is why `guard` defaults to
    the caller's choice rather than always on.
    """
    hw = Hwtest(link)
    for line in hw.connect():
        _say(f"< {line}")
    if not hw.is_hwtest():
        _say("Das ist nicht die hwtest-Firmware. Erst 'make hwtest-flash'.")
        return 1

    hw.command(f"us {step_us}")
    hw.command(f"guard {1 if guard else 0}")
    for line in hw.command("en 1"):
        _say(f"  {line}")

    timeout = steps * step_us * 4e-6 + 30
    bad = 0
    for axis in axes:
        _say(f"\n--- {axis}: {steps} Schritte vor, {pause:g} s Pause, zurueck ---")
        lines = hw.command(f"bounce {axis} {steps}", timeout=timeout)
        for line in lines:
            _say(f"  {line}")
        issued = parse_stepped(lines)
        if issued is not None and issued < steps:
            _say(f"  -> nur {issued}/{steps} Schritte")
            bad += 1
    hw.command("en 0")
    _say("\nTreiber wieder stromlos.")
    return 1 if bad else 0


def _diagnose(axis: str, auto: bool) -> str:
    """Narrow down why an axis did not move."""
    if auto:
        return "keine Bewegung"
    _say(f"    Fehlersuche {axis}:")
    if _ask("Brummt oder zittert der Motor, statt zu drehen?", auto):
        return ("Motor brummt - Spulenpaare vertauscht. Die vier Adern sind "
                "2 Paare (A+/A-, B+/B-); ein Paar muss zusammen bleiben.")
    if not _ask("Ist der Motor ueberhaupt bestromt (Welle blockiert)?", auto):
        return ("Motor stromlos - Treiber falsch herum eingesteckt, "
                "Vref am Trimmer auf 0, oder Motorstecker ab.")
    return ("Motor haelt, dreht aber nicht - STEP-Signal kommt nicht an. "
            "Treiber tauschen und nochmal messen.")


def _monitor(link, seconds: float = 60.0) -> None:
    """Stream the firmware's endstop monitor until the user presses enter."""
    import select

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        line = link.read_line(timeout=0.3)
        if line and line.startswith("endstops:"):
            print(f"    {line}", end="\r", flush=True)
        if select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.readline()
            break
    print()
    link.write_line("")          # any byte stops the firmware's monitor loop
    time.sleep(0.3)
    link.drain()
