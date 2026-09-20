/*
 * gt2560_pins.h - Geeetech GT2560 pin map, Arduino-Mega pin numbers.
 *
 * The GT2560 is NOT RAMPS pin compatible. Numbers below are taken from the
 * Marlin pin files (Marlin/src/pins/mega/pins_GT2560_*.h) which in turn follow
 * the Geeetech schematics:
 *   Rev.A / Rev.A+  https://www.geeetech.com/wiki/images/9/90/GT2560_sch.pdf
 *   V3              pins_GT2560_V3.h
 *
 * Select the revision with -DGT2560_REV_A (default) or -DGT2560_V3.
 */
#pragma once

#if !defined(GT2560_REV_A) && !defined(GT2560_V3)
  #define GT2560_REV_A
#endif
#if defined(GT2560_REV_A) && defined(GT2560_V3)
  #error "Define only one of GT2560_REV_A / GT2560_V3"
#endif

// ---------------------------------------------------------------- steppers --
// Slot order below is the *board silkscreen* order (X, Y, Z, E0, E1).
// The foam cutter axis mapping (which slot is X/Y/U/V) lives in main.cpp.

#if defined(GT2560_REV_A)
  #define BOARD_NAME "GT2560 Rev.A / Rev.A+"
  #define PIN_STEP_X   25
  #define PIN_DIR_X    23
  #define PIN_EN_X     27
  #define PIN_STEP_Y   31
  #define PIN_DIR_Y    33
  #define PIN_EN_Y     29
  #define PIN_STEP_Z   37
  #define PIN_DIR_Z    39
  #define PIN_EN_Z     35
  #define PIN_STEP_E0  43
  #define PIN_DIR_E0   45
  #define PIN_EN_E0    41
  #define PIN_STEP_E1  49
  #define PIN_DIR_E1   47
  #define PIN_EN_E1    48
  // Endstops
  #define PIN_X_MIN    22
  #define PIN_X_MAX    24
  #define PIN_Y_MIN    26
  #define PIN_Y_MAX    28
  #define PIN_Z_MIN    30
  #define PIN_Z_MAX    32
  // Spare inputs for a fourth axis: EXP2-7 (D38, SD card detect) and EXP2-5
  // (D40). The machine's four switches are wired to the X and Y connector
  // pairs instead (X -> X_MIN, Y -> X_MAX, U -> Y_MIN, V -> Y_MAX); see
  // docs/gt2560_pinout.md and cpu_map_gt2560.h.
  #define PIN_EXP2_7   38
  #define PIN_EXP2_5   40
  // Power outputs (low-side MOSFETs)
  #define PIN_HEATER_0  2   // OC3B - PWM capable, timer3
  #define PIN_HEATER_1  3   // OC3C - PWM capable, timer3
  #define PIN_HEATER_BED 4  // OC0B - timer0, DO NOT PWM under grbl (timer0 is grbl's)
  #define PIN_FAN       7   // OC4B
#else
  #define BOARD_NAME "GT2560 V3"
  #define PIN_STEP_X   37
  #define PIN_DIR_X    39
  #define PIN_EN_X     35
  #define PIN_STEP_Y   31
  #define PIN_DIR_Y    33
  #define PIN_EN_Y     29
  #define PIN_STEP_Z   25
  #define PIN_DIR_Z    23
  #define PIN_EN_Z     27
  #define PIN_STEP_E0  46
  #define PIN_DIR_E0   44
  #define PIN_EN_E0    12
  #define PIN_STEP_E1  49
  #define PIN_DIR_E1   47
  #define PIN_EN_E1    48
  // V3 swaps min/max relative to Rev.A
  #define PIN_X_MIN    24
  #define PIN_X_MAX    22
  #define PIN_Y_MIN    28
  #define PIN_Y_MAX    26
  #define PIN_Z_MIN    30
  #define PIN_Z_MAX    32
  #define PIN_EXP2_7   38
  #define PIN_EXP2_5   40


  #define PIN_HEATER_0 10
  #define PIN_HEATER_1  3
  #define PIN_HEATER_BED 4
  #define PIN_FAN       9
#endif

// ------------------------------------------------------------- hot wire ----
// The wire is driven from HEATER_1 (D3). Rationale in docs/gt2560_pinout.md:
// it is PWM capable on timer3, which grbl-Mega-5X does not use, so the same
// pin works for both this self-test and the production firmware.
#define PIN_HOTWIRE  PIN_HEATER_1

#define DRIVER_ENABLE_ACTIVE_LOW 1
