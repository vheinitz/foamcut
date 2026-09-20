# Superseded

This sketch drives **RAMPS 1.4 pin numbers** (X = D54/D55/D38) on a GT2560,
whose X driver is on D25/D23/D27. It toggles pins that are not connected to
anything, so the motors never move and nothing reports an error.

Use `firmware/hwtest/` instead — same idea, correct pin map, plus endstop
readout, a hot wire output with a dead-man timer, and a serial console.

    make hwtest-flash
    make monitor

If you specifically want a plain Arduino IDE `.ino` (no PlatformIO) with the
correct GT2560 pins and a simple X/Y/Z/U console, use
**[`../gt2560_motortest/`](../gt2560_motortest/)**.
