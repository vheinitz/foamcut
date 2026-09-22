#!/usr/bin/env python3
"""Turn a pristine grbl-Mega-5X checkout into the foamcut XYUV / GT2560 build.

Every edit is anchored on an exact upstream line and verified: if upstream
changes a line we depend on, this script fails loudly instead of silently
producing a firmware with the wrong pin map.

    ./configure.py <path-to-grbl-Mega-5X-checkout> [--serial usb|esp] [--hw-limits]

--serial esp   grbl talks on UART1 (TX1 = D18, RX1 = D19 on EXP1 pins 1/2)
               instead of UART0 (the USB chip): for an ESP32 running ESP3D
               in front of the board, see docs/esp32.md. The USB port is
               then silent.
--hw-limits    ENABLE_RAMPS_HW_LIMITS: $21=1 stops the machine from inside
               the firmware when a switch is hit during a move (polled in
               the stepper ISR - no pin change interrupt on the GT2560).
               Needed as soon as programs run without the PC watching.
"""
import re
import sys
from pathlib import Path

FOAMCUT_BLOCK = """
// ---------------------------------------------------------------------------
// foamcut: GT2560 XYUV hot wire cutter
//
// Hard limits are polled from the stepper ISR because no GT2560 endstop input
// sits on a pin change interrupt capable port. Uncomment to let $21=1 work,
// at the cost of some maximum step rate.
//#define ENABLE_RAMPS_HW_LIMITS
//
// Uncomment if you fitted a switch at both ends of every axis.
//#define LIMITS_TWO_SWITCHES_ON_AXES
// ---------------------------------------------------------------------------
"""


class PatchError(RuntimeError):
    pass


class File:
    def __init__(self, path):
        self.path = path
        if not path.exists():
            raise PatchError(f"{path} does not exist")
        self.text = path.read_text()
        self.edits = 0

    def sub(self, old, new, count=1, why=""):
        n = self.text.count(old)
        if n != count:
            raise PatchError(
                f"{self.path.name}: expected {count} occurrence(s) of\n"
                f"    {old!r}\nbut found {n}. Upstream changed; update configure.py."
            )
        self.text = self.text.replace(old, new, count)
        self.edits += 1
        print(f"  [ok] {self.path.name}: {why or old.strip()[:60]}")

    def sub_in_block(self, start_anchor, old, new, why=""):
        """Replace `old` only in the first block that starts at `start_anchor`."""
        i = self.text.find(start_anchor)
        if i < 0:
            raise PatchError(f"{self.path.name}: anchor not found: {start_anchor!r}")
        head, tail = self.text[:i], self.text[i:]
        if tail.count(old) < 1:
            raise PatchError(f"{self.path.name}: {old!r} not found after anchor")
        self.text = head + tail.replace(old, new, 1)
        self.edits += 1
        print(f"  [ok] {self.path.name}: {why}")

    def save(self):
        self.path.write_text(self.text)


SERIAL_REGS = ["UDR0", "UCSR0A", "UCSR0B", "UBRR0H", "UBRR0L", "U2X0", "RXEN0", "TXEN0", "RXCIE0", "UDRIE0"]


def main(root, serial="usb", hw_limits=False):
    grbl = root / "grbl"
    if not (grbl / "config.h").exists():
        raise PatchError(f"{root} does not look like a grbl-Mega-5X checkout")

    overlay = Path(__file__).parent / "overlay" / "cpu_map_gt2560.h"
    target = grbl / "cpu_map_gt2560.h"
    text = overlay.read_text()
    if serial == "esp":
        text = text.replace("USART0_RX_vect", "USART1_RX_vect").replace("USART0_UDRE_vect", "USART1_UDRE_vect")
    target.write_text(text)
    print(f"  [ok] installed {target.name}" + (" (UART1)" if serial == "esp" else ""))

    # ------------------------------------------------------------- serial.c --
    if serial == "esp":
        sc = File(grbl / "serial.c")
        for reg in SERIAL_REGS:
            n = len(re.findall(rf"\b{reg}\b", sc.text))
            if n == 0:
                raise PatchError(f"serial.c: register {reg} not found - upstream changed, update configure.py")
            sc.text = re.sub(rf"\b{reg}\b", reg.replace("0", "1", 1), sc.text)
        sc.text = "// foamcut: UART1 (D18/D19, EXP1) instead of the USB UART0 - see docs/esp32.md\n" + sc.text
        sc.edits += 1
        print("  [ok] serial.c: UART0 registers -> UART1")
        sc.save()

    # ------------------------------------------------------------ cpu_map.h --
    cm = File(grbl / "cpu_map.h")
    if "cpu_map_gt2560.h" not in cm.text:
        # The header ends with the guard's #endif; hook the include in front of it.
        marker = "#endif // CPU_MAP_2560_RAMPS_BOARD"
        cm.sub(
            marker,
            marker + '\n\n#ifdef CPU_MAP_2560_GT2560\n  #include "cpu_map_gt2560.h"\n#endif\n',
            why="hook CPU_MAP_2560_GT2560 include",
        )
    cm.save()

    # ------------------------------------------------------------- config.h --
    cf = File(grbl / "config.h")
    cf.sub(
        "#define CPU_MAP_2560_RAMPS_BOARD",
        "//#define CPU_MAP_2560_RAMPS_BOARD\n#define CPU_MAP_2560_GT2560\n" + FOAMCUT_BLOCK,
        why="select the GT2560 pin map",
    )
    if hw_limits:
        cf.sub("//#define ENABLE_RAMPS_HW_LIMITS\n", "#define ENABLE_RAMPS_HW_LIMITS   // foamcut: --hw-limits\n",
               why="hard limits polled in the stepper ISR ($21=1 works)")
    cf.sub("#define N_AXIS 5", "#define N_AXIS 4", why="N_AXIS = 4")
    cf.sub("#define N_AXIS_LINEAR 3", "#define N_AXIS_LINEAR 4",
           why="all four axes are linear")
    cf.sub("#define AXIS_3_NAME 'Z'", "#define AXIS_3_NAME 'U'",
           why="axis 3 is U (right tower, horizontal)")
    cf.sub("#define AXIS_4_NAME 'A'", "#define AXIS_4_NAME 'V'",
           why="axis 4 is V (right tower, vertical)")
    cf.sub("#define SPINDLE_PWM_ON_D8", "//#define SPINDLE_PWM_ON_D8",
           why="hot wire PWM pin comes from cpu_map_gt2560.h")
    # The four switches are normally closed (S to GND, open when hit). grbl's
    # $5 cannot express that here: grbl-Mega-5X ANDs the MIN and MAX inputs
    # when $5=1, and the unwired MAX inputs would make every axis look hit.
    # So $5 stays 0 and only the MIN inputs are inverted at compile time.
    cf.sub("//#define INVERT_MIN_LIMIT_PIN_MASK ((1<<AXIS_1) | (1<<AXIS_2) | (1<<AXIS_3))",
           "#define INVERT_MIN_LIMIT_PIN_MASK ((1<<AXIS_1) | (1<<AXIS_2) | (1<<AXIS_3) | (1<<AXIS_4))  // foamcut: NC switches",
           why="normally closed limit switches on all four MIN inputs")

    # A foam cutter has no Z to lift, so all four axes home together.
    cf.sub_in_block(
        "#if N_AXIS == 4 // 4 axis : homing",
        "  #define HOMING_CYCLE_0 (1<<AXIS_3) // Home Z axis first to clear workspace.\n"
        "  #define HOMING_CYCLE_1 ((1<<AXIS_1)|(1<<AXIS_2))     "
        "// OPTIONAL: uncomment to move X,Y at the same time.\n",
        "  // foamcut: no Z to retract - home all four towers simultaneously.\n"
        "  #define HOMING_CYCLE_0 ((1<<AXIS_1)|(1<<AXIS_2)|(1<<AXIS_3)|(1<<AXIS_4))\n",
        why="home X Y U V in one cycle",
    )
    cf.save()

    # ------------------------------------------------------------ defaults.h --
    df = File(grbl / "defaults.h")
    for n in (1, 2, 3):
        df.sub(f"#define MICROSTEPS_AXIS{n} 4     // Microstepping = 1/4 pas",
               f"#define MICROSTEPS_AXIS{n} 16    // GT2560 with A4988 at 1/16",
               why=f"axis {n} microstepping 1/16")
        df.sub(f"#define UNIT_PER_REV_AXIS{n} 2.0 // 2mm",
               f"#define UNIT_PER_REV_AXIS{n} 8.0 // T8 lead screw, 8 mm per turn",
               why=f"axis {n} lead 8 mm/rev")
    # 'V' is not X/Y/U, so upstream would give axis 4 rotary degrees-per-unit
    # defaults. It is a linear axis here; mirror axis 2 (the other vertical).
    df.sub(
        "        #define DEFAULT_AXIS4_STEPS_PER_UNIT 8.888889 "
        "// Direct drive : (200 pas par tours * 1/16 microsteps)/360°\n"
        "        #define DEFAULT_AXIS4_MAX_RATE 1440 // °/mn\n"
        "        #define DEFAULT_AXIS4_ACCELERATION (50.0*60*60) "
        "// 100*60*60 mm/min^2 = 100 mm/sec^2\n"
        "        #define DEFAULT_AXIS4_MAX_TRAVEL 360.0 // °\n",
        "        // foamcut: V is a linear axis, same mechanics as Y.\n"
        "        #define DEFAULT_AXIS4_STEPS_PER_UNIT DEFAULT_AXIS2_STEPS_PER_UNIT\n"
        "        #define DEFAULT_AXIS4_MAX_RATE DEFAULT_AXIS2_MAX_RATE\n"
        "        #define DEFAULT_AXIS4_ACCELERATION DEFAULT_AXIS2_ACCELERATION\n"
        "        #define DEFAULT_AXIS4_MAX_TRAVEL DEFAULT_AXIS2_MAX_TRAVEL\n",
        why="axis 4 (V) is linear, not rotary",
    )
    df.save()

    print("configure: done")


if __name__ == "__main__":
    args = sys.argv[1:]
    serial, hw = "usb", False
    if "--hw-limits" in args:
        hw = True; args.remove("--hw-limits")
    if "--serial" in args:
        i = args.index("--serial")
        serial = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if len(args) != 1 or serial not in ("usb", "esp"):
        print(__doc__)
        sys.exit(2)
    try:
        main(Path(args[0]).resolve(), serial=serial, hw_limits=hw)
    except PatchError as e:
        print(f"configure: ERROR: {e}", file=sys.stderr)
        sys.exit(1)
