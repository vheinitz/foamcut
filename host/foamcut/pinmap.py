"""ATmega2560 pin bookkeeping.

The two firmwares in this project name the same physical pins in two different
ways: firmware/hwtest uses Arduino pin numbers, firmware/grbl5x uses raw AVR
port and bit. A transcription slip between them is silent and expensive - the
motor simply does not turn - so both files are parsed and compared by the test
suite.
"""
from __future__ import annotations

import re
from pathlib import Path

# Arduino Mega 2560 digital pin -> (port letter, bit). From the Arduino core's
# pins_arduino.h for the mega variant.
MEGA_PIN: dict[int, tuple[str, int]] = {}


def _fill(start: int, port: str, bits: list[int]) -> None:
    for offset, bit in enumerate(bits):
        MEGA_PIN[start + offset] = (port, bit)


_fill(0, "E", [0, 1])
MEGA_PIN[2] = ("E", 4)
MEGA_PIN[3] = ("E", 5)
MEGA_PIN[4] = ("G", 5)
MEGA_PIN[5] = ("E", 3)
_fill(6, "H", [3, 4, 5, 6])
_fill(10, "B", [4, 5, 6, 7])
MEGA_PIN[14] = ("J", 1)
MEGA_PIN[15] = ("J", 0)
MEGA_PIN[16] = ("H", 1)
MEGA_PIN[17] = ("H", 0)
_fill(18, "D", [3, 2, 1, 0])
_fill(22, "A", [0, 1, 2, 3, 4, 5, 6, 7])
_fill(30, "C", [7, 6, 5, 4, 3, 2, 1, 0])
MEGA_PIN[38] = ("D", 7)
_fill(39, "G", [2, 1, 0])
_fill(42, "L", [7, 6, 5, 4, 3, 2, 1, 0])
_fill(50, "B", [3, 2, 1, 0])
_fill(54, "F", [0, 1, 2, 3, 4, 5, 6, 7])
_fill(62, "K", [0, 1, 2, 3, 4, 5, 6, 7])

PORT_BIT_TO_PIN = {v: k for k, v in MEGA_PIN.items()}


def pin_of(port: str, bit: int) -> int:
    """('A', 3) -> 25. Raises KeyError for a pin the Mega does not break out."""
    return PORT_BIT_TO_PIN[(port.upper(), bit)]


def name_of(pin: int) -> str:
    """25 -> 'D25 / PA3'"""
    port, bit = MEGA_PIN[pin]
    return f"D{pin} / P{port}{bit}"


# ------------------------------------------------------------- file readers --
_DEFINE = re.compile(r"^\s*#define\s+(\w+)\s+(\S+)", re.M)


def read_defines(path: Path) -> dict[str, str]:
    """Flat `#define NAME VALUE` pairs; the last definition of a name wins."""
    return {m.group(1): m.group(2) for m in _DEFINE.finditer(path.read_text())}


def read_hwtest_pins(path: Path, revision: str = "GT2560_REV_A") -> dict[str, int]:
    """PIN_* numbers from the selected revision branch of gt2560_pins.h."""
    text = path.read_text()
    start = text.index(f"#if defined({revision})")
    end = text.index("#else", start) if revision == "GT2560_REV_A" else text.index("#endif", start)
    out = {}
    for m in _DEFINE.finditer(text[start:end]):
        name, value = m.group(1), m.group(2)
        if name.startswith("PIN_") and value.lstrip("-").isdigit():
            out[name] = int(value)
    return out


def read_grbl_pin(defines: dict[str, str], port_key: str, bit_key: str) -> int:
    """Resolve a grbl PORT/BIT pair to an Arduino pin number.

    Accepts both spellings used in cpu_map files: a bare port letter
    (`#define STEP_PORT_0 A`) and a full register name (`#define
    SPINDLE_PWM_PORT PORTE`).
    """
    port = defines[port_key]
    if port.startswith(("PORT", "DDR", "PIN")):
        port = port[-1]
    return pin_of(port, int(defines[bit_key]))
