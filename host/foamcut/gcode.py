"""Parse, validate and generate 4 axis (XYUV) hot wire G-code.

Nothing in here talks to hardware, so a G-code file can be checked before the
machine is even switched on.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import AXES

_WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_LINE_COMMENT = re.compile(r";.*$")
_INLINE_COMMENT = re.compile(r"\([^)]*\)")

# What grbl-Mega-5X 1.2i actually accepts. Anything else in a file is a hard
# error at run time ("error:20 Unsupported command"), which is exactly the
# trap the 4AxisFoamCutter README warns about for Jedicut and WingGcode output.
SUPPORTED_G = {
    "0", "1", "2", "3", "4", "10", "17", "18", "19", "20", "21", "28", "28.1",
    "30", "30.1", "38.2", "38.3", "38.4", "38.5", "40", "43.1", "49", "53",
    "54", "55", "56", "57", "58", "59", "61", "80", "90", "91", "92", "92.1",
    "93", "94",
}
SUPPORTED_M = {
    "0", "1", "2", "3", "4", "5", "7", "8", "9", "30", "56", "62", "63", "64",
    "65",
}


def strip_comments(line: str) -> str:
    return _LINE_COMMENT.sub("", _INLINE_COMMENT.sub(" ", line)).strip()


def parse_words(line: str) -> list[tuple[str, float]]:
    """['G', 1.0], ['X', 10.0] ... for one line, comments removed."""
    return [(m.group(1).upper(), float(m.group(2)))
            for m in _WORD.finditer(strip_comments(line))]


def _fmt_code(value: float) -> str:
    """1.0 -> '1', 38.2 -> '38.2' - G-code numbers keep a meaningful decimal."""
    return f"{value:g}"


@dataclass
class Move:
    line_no: int
    rapid: bool
    start: dict[str, float]
    end: dict[str, float]
    feed: float | None
    inverse_time: bool = False   # G93: feed is 1/min, move takes 1/F minutes

    def deltas(self) -> dict[str, float]:
        return {a: self.end[a] - self.start[a] for a in AXES}

    def length(self) -> float:
        """Path length the way grbl measures it.

        grbl-Mega-5X is built here with N_AXIS_LINEAR = 4, so the feed rate
        applies to the euclidean norm over *all four* axes, not to the speed of
        an individual tower. A move where both towers travel 100 mm has a
        length of 141 mm, so at F300 each tower actually runs at 212 mm/min.
        """
        return math.sqrt(sum(d * d for d in self.deltas().values()))

    def tower_length(self) -> float:
        """Distance the faster of the two towers travels - what the foam sees."""
        d = self.deltas()
        return max(math.hypot(d["X"], d["Y"]), math.hypot(d["U"], d["V"]))


@dataclass
class Program:
    moves: list[Move] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------- parsing --
    @classmethod
    def parse(cls, text: str, start: dict[str, float] | None = None) -> "Program":
        """`start`: where the carriages are when the program begins (work
        coordinates); matters for relative programs such as a Freischnitt."""
        prog = cls()
        pos = {a: 0.0 for a in AXES}
        if start:
            pos.update(start)
        absolute = True
        scale = 1.0          # G20 inch -> mm
        rapid = True         # modal motion; grbl starts in G0
        inverse = False      # G93 inverse time / G94 units per minute
        feed: float | None = None
        seen_feed = False
        line_feed = False    # F word on this very line

        for n, raw in enumerate(text.splitlines(), start=1):
            words = parse_words(raw)
            if not words:
                continue

            motion_this_line = None
            axis_words: dict[str, float] = {}
            line_feed = False

            for letter, value in words:
                if letter == "G":
                    code = _fmt_code(value)
                    if code not in SUPPORTED_G:
                        prog.errors.append(f"line {n}: G{code} is not supported by grbl")
                        continue
                    if code == "0":
                        rapid = True
                        motion_this_line = True
                    elif code == "1":
                        rapid = False
                        motion_this_line = True
                    elif code == "90":
                        absolute = True
                    elif code == "91":
                        absolute = False
                    elif code == "20":
                        scale = 25.4
                        prog.warnings.append(f"line {n}: G20, file is in inches")
                    elif code == "21":
                        scale = 1.0
                    elif code == "93":
                        inverse = True
                        feed = None      # grbl: feed undefined until an F word
                    elif code == "94":
                        if inverse:
                            feed = None  # G93 -> G94: grbl forgets the feed rate
                        inverse = False
                elif letter == "M":
                    code = _fmt_code(value)
                    if code not in SUPPORTED_M:
                        prog.errors.append(f"line {n}: M{code} is not supported by grbl")
                elif letter in AXES:
                    axis_words[letter] = value * scale
                elif letter == "F":
                    feed = value if inverse else value * scale
                    seen_feed = True
                    line_feed = True
                elif letter in ("S", "P", "T", "N", "I", "J", "K", "R", "L"):
                    pass
                elif letter in ("Z", "A", "B", "C"):
                    prog.errors.append(
                        f"line {n}: axis word {letter} - this build uses X Y U V"
                    )
                else:
                    prog.warnings.append(f"line {n}: ignoring word {letter}{value:g}")

            if not axis_words:
                continue
            if motion_this_line is None and not prog.moves and not seen_feed:
                prog.warnings.append(
                    f"line {n}: motion before any G0/G1, assuming the modal default"
                )

            start = dict(pos)
            end = dict(pos)
            for a, v in axis_words.items():
                end[a] = v if absolute else pos[a] + v
            pos = end

            if not rapid and inverse and not line_feed:
                prog.errors.append(f"line {n}: G93 needs an F word on every G1 line")
            elif not rapid and feed is None:
                prog.errors.append(f"line {n}: G1 without a feed rate")

            prog.moves.append(Move(n, rapid, start, end, feed, inverse))

        if not prog.moves:
            prog.warnings.append("file contains no motion")
        return prog

    # ------------------------------------------------------------ analysis --
    def extents(self) -> dict[str, tuple[float, float]]:
        out = {}
        for a in AXES:
            vals = [0.0] + [m.end[a] for m in self.moves]
            out[a] = (min(vals), max(vals))
        return out

    def duration_s(self, rapid_feed: float = 1500.0) -> float:
        """Rough run time. Ignores acceleration, so this is a lower bound."""
        total = 0.0
        for m in self.moves:
            if m.inverse_time and not m.rapid and m.feed:
                total += 60.0 / m.feed          # G93: F = 1 / minutes
                continue
            f = rapid_feed if m.rapid else (m.feed or rapid_feed)
            if f <= 0:
                continue
            total += m.length() / f * 60.0
        return total

    def max_tower_feed_ratio(self) -> float:
        """Largest (tower speed / commanded feed) in the program.

        1.0 means the towers move at exactly the commanded feed. Values above
        1.0 cannot happen; values well below 1.0 mean the four axis vector
        feed makes the wire travel slower through the foam than the number in
        the file suggests.
        """
        worst = 1.0
        for m in self.moves:
            if m.inverse_time:
                continue                        # feed is a time, not a speed
            L = m.length()
            if L <= 0:
                continue
            worst = min(worst, m.tower_length() / L)
        return worst

    def report(self) -> str:
        lines = [f"{len(self.moves)} moves"]
        for a, (lo, hi) in self.extents().items():
            lines.append(f"  {a}: {lo:9.3f} .. {hi:9.3f} mm   (travel {hi - lo:.3f})")
        lines.append(f"  estimated run time: {self.duration_s() / 60:.1f} min")
        inv = sum(1 for m in self.moves if m.inverse_time)
        if inv:
            lines.append(f"  {inv} moves in G93 inverse time mode (F = 1/min, grbl supports it)")
        ratio = self.max_tower_feed_ratio()
        if ratio < 0.999:
            lines.append(
                f"  note: with both towers moving, wire speed drops to "
                f"{ratio * 100:.0f} % of the commanded feed (4 axis vector feed)"
            )
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        return "\n".join(lines)


# --------------------------------------------------------------- generators --
def _header(title: str) -> list[str]:
    return [f"; {title}", "G21 ; mm", "G90 ; absolute", "G94 ; units per minute"]


def gen_square(size: float = 50.0, feed: float = 300.0) -> str:
    """A prismatic block: both towers trace the same square.

    Proves that X/Y and U/V stay in step. If the two towers disagree, the cut
    comes out twisted.
    """
    out = _header(f"square {size} mm, both towers identical")
    out.append(f"G1 F{feed:g}")
    corners = [(0, 0), (size, 0), (size, size), (0, size), (0, 0)]
    for x, y in corners:
        out.append(f"G1 X{x:.3f} Y{y:.3f} U{x:.3f} V{y:.3f}")
    out.append("M2")
    return "\n".join(out) + "\n"


def gen_taper(root: float = 60.0, tip: float = 30.0, height: float = 40.0,
              feed: float = 300.0) -> str:
    """A tapered block: left tower cuts `root`, right tower cuts `tip`.

    This is the test that a 3 axis controller cannot pass. The two towers run
    different distances in the same move, which is the whole point of XYUV.
    """
    out = _header(f"taper: left {root} mm, right {tip} mm, height {height} mm")
    out.append(f"G1 F{feed:g}")
    left = [(0, 0), (root, 0), (root, height), (0, height), (0, 0)]
    right = [(0, 0), (tip, 0), (tip, height), (0, height), (0, 0)]
    for (x, y), (u, v) in zip(left, right):
        out.append(f"G1 X{x:.3f} Y{y:.3f} U{u:.3f} V{v:.3f}")
    out.append("M2")
    return "\n".join(out) + "\n"


def gen_axis_bounce(axis: str, distance: float = 50.0, feed: float = 300.0) -> str:
    """Move one axis out and back - the calibration move for steps/mm."""
    axis = axis.upper()
    if axis not in AXES:
        raise ValueError(f"axis must be one of {AXES}, got {axis!r}")
    out = _header(f"{axis} axis: {distance} mm out and back")
    out += [
        "G91 ; relative",
        f"G1 {axis}{distance:.3f} F{feed:g}",
        "G4 P1",
        f"G1 {axis}{-distance:.3f} F{feed:g}",
        "G90",
        "M2",
    ]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------- translate --
# Axis letter conventions of the common wing G-code generators. Tower 1 is
# always X/Y; tower 2 differs.
AXIS_PRESETS = {
    "XYUV": {},                              # ours, Jedicut, WingGcode
    "XYAZ": {"A": "U", "Z": "V"},            # hotwireairfoil.coolpixx.de: A horizontal, Z vertical
    "XYZA": {"Z": "U", "A": "V"},            # LinuxCNC style foam configs: Z horizontal, A vertical
}
DROP_CODES = {"G64", "G61.1", "M6"}          # accepted by many senders, fatal in grbl

_AXIS_WORD = re.compile(r"(?<![A-Za-z])([A-Za-z])(\s*[-+]?(?:\d+\.?\d*|\.\d+))")


def detect_axis_preset(text: str) -> str:
    """Which letters a file uses for tower 2. 'XYUV' when it already fits."""
    letters = set()
    for line in text.splitlines():
        for letter, _ in parse_words(line):
            if letter in ("U", "V", "A", "Z"):
                letters.add(letter)
    if letters & {"U", "V"}:
        return "XYUV"
    if letters == {"A", "Z"}:
        return "XYAZ"       # the numbers cannot tell A/Z apart; XYAZ is the more common one
    return "XYUV"


def translate(text: str, preset: str = "auto", wire_power: int | None = None,
              default_feed: float | None = None) -> tuple[str, list[str]]:
    """Make a generator's file grbl/XYUV ready. Returns (text, notes)."""
    if preset == "auto":
        preset = detect_axis_preset(text)
    axis_map = AXIS_PRESETS[preset]
    notes: list[str] = []
    if axis_map:
        notes.append(f"Achsformat {preset}: " + ", ".join(f"{a}->{b}" for a, b in axis_map.items()))
    out: list[str] = []
    dropped: dict[str, int] = {}
    inverse = False
    feed_defined = True
    feed_injected = 0
    wire_fixed = 0

    for raw in text.splitlines():
        words = parse_words(raw)
        if not words:
            out.append(raw)
            continue

        gcodes = {f"G{_fmt_code(v)}" for l, v in words if l == "G"}
        mcodes = {f"M{_fmt_code(v)}" for l, v in words if l == "M"}
        drop = (gcodes | mcodes) & DROP_CODES
        if drop:
            for d in drop:
                dropped[d] = dropped.get(d, 0) + 1
            out.append(f"; foamcut: entfernt ({', '.join(sorted(drop))}) {raw.strip()}")
            continue

        if "G93" in gcodes:
            inverse = True
        if "G94" in gcodes:
            if inverse:
                feed_defined = False
            inverse = False
        if any(l == "F" for l, _ in words):
            feed_defined = True

        line = raw
        if axis_map:
            def _sub(m):
                letter = m.group(1).upper()
                return axis_map.get(letter, m.group(1)) + m.group(2)
            body, sep, tail = line.partition(";")
            line = _AXIS_WORD.sub(_sub, body) + sep + tail

        has_motion = any(l in AXES or l in axis_map for l, _ in words)
        is_feed_move = ("G1" in gcodes) or (has_motion and not gcodes & {"G0", "G28", "G30", "G92", "G10"})
        if (not inverse and not feed_defined and is_feed_move
                and "G1" in gcodes and default_feed):
            body, sep, tail = line.partition(";")
            line = f"{body.rstrip()} F{default_feed:g} " + (sep + tail if sep else "")
            feed_defined = True
            feed_injected += 1

        if "M3" in mcodes or "M4" in mcodes:
            s = [v for l, v in words if l == "S"]
            if s and s[0] <= 1 and wire_power:
                body, sep, tail = line.partition(";")
                body = re.sub(r"S\s*[-+]?\d+\.?\d*", f"S{int(wire_power)}", body, count=1)
                line = body + sep + tail
                wire_fixed += 1
            elif s and s[0] <= 1:
                notes.append(f"M3 S{s[0]:g}: Relais-Logik des Generators - bei uns 0,4 % PWM, "
                             "Draht bleibt kalt. Drahtleistung setzen (GUI-Schieber / --wire).")
        out.append(line)

    for d, n in sorted(dropped.items()):
        notes.append(f"{d} entfernt ({n}x, grbl kennt es nicht)")
    if feed_injected:
        notes.append(f"F{default_feed:g} ergaenzt ({feed_injected}x: G1 ohne Vorschub nach G94)")
    if wire_fixed:
        notes.append(f"M3 S -> S{int(wire_power)} ({wire_fixed}x)")
    return "\n".join(out) + "\n", notes
