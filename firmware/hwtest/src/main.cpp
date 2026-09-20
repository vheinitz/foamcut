/*
 * foamcut hwtest - bring-up self test for a GT2560 driven XYUV hot wire cutter.
 *
 * This firmware deliberately contains NO motion planner. It bit-bangs single
 * axes so that a wiring / driver / endstop fault can be isolated before grbl
 * is flashed. Everything is driven from a line oriented serial console at
 * 115200 baud.
 *
 * Safety: the hot wire output is on a dead-man timer. It switches off by
 * itself HOTWIRE_TIMEOUT_MS after the last console line, so a lost USB
 * connection cannot leave the wire glowing.
 */
#include <Arduino.h>
#include "gt2560_pins.h"

// ---------------------------------------------------------------- tuning --
static const uint32_t BAUD              = 115200;
static const uint16_t DEFAULT_STEP_US   = 400;   // half period per step pulse
static const uint16_t MIN_STEP_US       = 1;    // 
static const uint32_t MAX_STEP_US       = 65535; // stepUs is uint16_t
static const uint32_t HOTWIRE_TIMEOUT_MS = 10000;

// ------------------------------------------------------------ axis table --
// Slot = physical driver socket on the board. Axis = foam cutter axis letter.
// Left tower  = X (horizontal) + Y (vertical)
// Right tower = U (horizontal) + V (vertical)
struct Axis {
  char     letter;
  const char *slot;
  uint8_t  step, dir, en;
  int8_t   minEs, maxEs;   // -1 = no endstop on this slot
};

static Axis axes[] = {
  // limit inputs as wired 2026-09-18: one switch per axis on the X/Y pairs
  { 'X', "X",  PIN_STEP_X,  PIN_DIR_X,  PIN_EN_X,  PIN_X_MIN, PIN_Z_MIN },
  { 'Y', "Y",  PIN_STEP_Y,  PIN_DIR_Y,  PIN_EN_Y,  PIN_X_MAX, PIN_Z_MAX },
  { 'U', "Z",  PIN_STEP_Z,  PIN_DIR_Z,  PIN_EN_Z,  PIN_Y_MIN, PIN_EXP2_7 },
  { 'V', "E0", PIN_STEP_E0, PIN_DIR_E0, PIN_EN_E0, PIN_Y_MAX, PIN_EXP2_5 },
  { '-', "E1", PIN_STEP_E1, PIN_DIR_E1, PIN_EN_E1, -1,        -1        },
};
static const uint8_t N_SLOTS = sizeof(axes) / sizeof(axes[0]);
static const uint8_t N_AXES  = 4;   // X Y U V; slot 4 (E1) is a spare

// ------------------------------------------------------------- run state --
static uint16_t stepUs      = DEFAULT_STEP_US;
static bool     driversOn   = false;
static bool     endstopGuard = true;
static uint8_t  hotwirePwm  = 0;
static uint32_t lastLineMs  = 0;

static const uint8_t EN_ON  = DRIVER_ENABLE_ACTIVE_LOW ? LOW  : HIGH;
static const uint8_t EN_OFF = DRIVER_ENABLE_ACTIVE_LOW ? HIGH : LOW;

// --------------------------------------------------------------- helpers --
static int findAxis(char c) {
  c = toupper(c);
  for (uint8_t i = 0; i < N_SLOTS; i++) if (axes[i].letter == c) return i;
  if (c >= '0' && c < char('0' + N_SLOTS)) return c - '0';
  return -1;
}

static void setDrivers(bool on) {
  driversOn = on;
  for (uint8_t i = 0; i < N_SLOTS; i++) digitalWrite(axes[i].en, on ? EN_ON : EN_OFF);
  Serial.print(F("drivers ")); Serial.println(on ? F("ENABLED") : F("released"));
}

static void setHotwire(uint8_t pwm) {
  hotwirePwm = pwm;
  analogWrite(PIN_HOTWIRE, pwm);
  Serial.print(F("hotwire pwm=")); Serial.print(pwm);
  Serial.print(F(" ("));  Serial.print((pwm * 100) / 255); Serial.println(F("%)"));
}

// Reads an endstop. Switches are wired to GND with the internal pull-up
// enabled, so LOW == triggered.
static bool endstopHit(int8_t pin) { return pin >= 0 && digitalRead(pin) == LOW; }

// Returns the number of steps actually issued (< steps if an endstop stopped us).
static long jog(uint8_t idx, long steps, bool forward) {
  Axis &a = axes[idx];
  digitalWrite(a.dir, forward ? HIGH : LOW);
  int8_t guardPin = endstopGuard ? (forward ? a.maxEs : a.minEs) : -1;
  delayMicroseconds(20);                       // DIR setup time for A4988/DRV8825

  long done = 0;
  for (long s = 0; s < steps; s++) {
    if (endstopHit(guardPin)) {
      Serial.print(F("! endstop on pin ")); Serial.print(guardPin);
      Serial.println(F(" triggered, stopping"));
      break;
    }
    digitalWrite(a.step, HIGH);
    delayMicroseconds(stepUs);
    digitalWrite(a.step, LOW);
    delayMicroseconds(stepUs);
    done++;
  }
  return done;
}

// Steps X, Y, U and V in lockstep. This is the hardware level proof that four
// axes can be driven simultaneously - the thing a 3-axis board cannot do.
static void jogAll(long steps, bool forward) {
  for (uint8_t i = 0; i < N_AXES; i++) {
    digitalWrite(axes[i].dir, forward ? HIGH : LOW);
  }
  delayMicroseconds(20);
  for (long s = 0; s < steps; s++) {
    for (uint8_t i = 0; i < N_AXES; i++) digitalWrite(axes[i].step, HIGH);
    delayMicroseconds(stepUs);
    for (uint8_t i = 0; i < N_AXES; i++) digitalWrite(axes[i].step, LOW);
    delayMicroseconds(stepUs);
  }
}

// ---------------------------------------------------------------- output --
static void printPinMap() {
  Serial.println(F("axis slot  step  dir   en   min  max"));
  for (uint8_t i = 0; i < N_SLOTS; i++) {
    Axis &a = axes[i];
    char buf[64];
    snprintf(buf, sizeof(buf), " %c   %-4s %4d %4d %4d %4d %4d",
             a.letter, a.slot, a.step, a.dir, a.en, a.minEs, a.maxEs);
    Serial.println(buf);
  }
  Serial.print(F("hotwire pin D")); Serial.println(PIN_HOTWIRE);
  Serial.print(F("fan     pin D")); Serial.println(PIN_FAN);
}

static void printEndstops() {
  Serial.print(F("endstops:"));
  for (uint8_t i = 0; i < N_SLOTS; i++) {
    if (axes[i].minEs < 0) continue;
    Serial.print(F("  ")); Serial.print(axes[i].letter);
    Serial.print(F("min=")); Serial.print(endstopHit(axes[i].minEs) ? '1' : '0');
    Serial.print(F(" "));    Serial.print(axes[i].letter);
    Serial.print(F("max=")); Serial.print(endstopHit(axes[i].maxEs) ? '1' : '0');
  }
  Serial.println();
}

static void printStatus() {
  Serial.print(F("board=")); Serial.print(F(BOARD_NAME));
  Serial.print(F(" drivers=")); Serial.print(driversOn ? F("on") : F("off"));
  Serial.print(F(" stepUs=")); Serial.print(stepUs);
  Serial.print(F(" guard=")); Serial.print(endstopGuard ? F("on") : F("off"));
  Serial.print(F(" hotwire=")); Serial.println(hotwirePwm);
}

static void printHelp() {
  Serial.println(F(
    "commands:\r\n"
    "  ?              this help\r\n"
    "  map            print pin map\r\n"
    "  st             print status\r\n"
    "  en 1|0         enable / release stepper drivers\r\n"
    "  us <n>         step half-period in microseconds (>=40)\r\n"
    "  guard 1|0      stop a jog when the endstop in the travel direction hits\r\n"
    "  j <axis> <n>   jog axis n steps forward (negative n = backward)\r\n"
    "                 axis is X Y U V, or the slot index 0..4\r\n"
    "  bounce <axis> <n>  jog forward n, pause, jog back n\r\n"
    "  all <n>        step X Y U V simultaneously, then back\r\n"
    "  es             read endstops once\r\n"
    "  mon            read endstops every 250 ms until a key is pressed\r\n"
    "  w <0-255>      hot wire PWM   (dead-man: off 10 s after last command)\r\n"
    "  w off          hot wire off\r\n"
    "  fan 1|0        board fan on / off\r\n"
    "  selftest       enable, bounce every axis, report endstops"));
}

// -------------------------------------------------------------- commands --
static void cmdSelftest() {
  Serial.println(F("--- selftest ---"));
  setDrivers(true);
  for (uint8_t i = 0; i < N_AXES; i++) {
    Serial.print(F("axis ")); Serial.print(axes[i].letter);
    Serial.print(F(" (slot ")); Serial.print(axes[i].slot); Serial.print(F("): "));
    long fwd = jog(i, 800, true);
    delay(300);
    long rev = jog(i, 800, false);
    Serial.print(fwd); Serial.print(F(" fwd / ")); Serial.print(rev);
    Serial.println(F(" rev steps"));
    delay(300);
  }
  printEndstops();
  Serial.println(F("--- selftest done, drivers still enabled ---"));
}

static void handle(char *line) {
  while (*line == ' ') line++;
  if (!*line) return;

  char *cmd = strtok(line, " ");
  char *a1  = strtok(NULL, " ");
  char *a2  = strtok(NULL, " ");

  if (!strcmp(cmd, "?") || !strcmp(cmd, "help")) { printHelp(); return; }
  if (!strcmp(cmd, "map")) { printPinMap(); return; }
  if (!strcmp(cmd, "st"))  { printStatus(); return; }
  if (!strcmp(cmd, "es"))  { printEndstops(); return; }

  if (!strcmp(cmd, "mon")) {
    Serial.println(F("monitoring, press any key to stop"));
    while (!Serial.available()) { printEndstops(); delay(250); }
    while (Serial.available()) Serial.read();
    return;
  }

  if (!strcmp(cmd, "en")) {
    if (!a1) { Serial.println(F("usage: en 1|0")); return; }
    setDrivers(atoi(a1) != 0);
    return;
  }

  if (!strcmp(cmd, "guard")) {
    if (!a1) { Serial.println(F("usage: guard 1|0")); return; }
    endstopGuard = atoi(a1) != 0;
    Serial.print(F("endstop guard ")); Serial.println(endstopGuard ? F("on") : F("off"));
    return;
  }

  if (!strcmp(cmd, "us")) {
    if (!a1) { Serial.println(F("usage: us <microseconds>")); return; }
    long v = atol(a1);
    if (v < MIN_STEP_US) { Serial.print(F("refusing, minimum is ")); Serial.println(MIN_STEP_US); return; }
    if (v > (long)MAX_STEP_US) { Serial.print(F("refusing, maximum is ")); Serial.println(MAX_STEP_US); return; }
    stepUs = (uint16_t)v;
    Serial.print(F("stepUs=")); Serial.println(stepUs);
    return;
  }

  if (!strcmp(cmd, "j") || !strcmp(cmd, "bounce")) {
    if (!a1 || !a2) { Serial.println(F("usage: j <axis> <steps>")); return; }
    int idx = findAxis(a1[0]);
    if (idx < 0) { Serial.println(F("unknown axis")); return; }
    long n = atol(a2);
    bool fwd = n >= 0;
    if (n < 0) n = -n;
    if (!driversOn) setDrivers(true);
    long done = jog(idx, n, fwd);
    Serial.print(F("stepped ")); Serial.println(done);
    if (!strcmp(cmd, "bounce")) {
      delay(1000);
      done = jog(idx, n, !fwd);
      Serial.print(F("stepped back ")); Serial.println(done);
    }
    return;
  }

  if (!strcmp(cmd, "all")) {
    if (!a1) { Serial.println(F("usage: all <steps>")); return; }
    long n = atol(a1);
    if (!driversOn) setDrivers(true);
    Serial.println(F("X Y U V forward..."));
    jogAll(n, true);
    delay(1000);
    Serial.println(F("X Y U V back..."));
    jogAll(n, false);
    Serial.println(F("done"));
    return;
  }

  if (!strcmp(cmd, "w")) {
    if (!a1) { Serial.println(F("usage: w <0-255> | w off")); return; }
    if (!strcmp(a1, "off")) { setHotwire(0); return; }
    long v = atol(a1);
    if (v < 0) v = 0;
    if (v > 255) v = 255;
    setHotwire((uint8_t)v);
    return;
  }

  if (!strcmp(cmd, "fan")) {
    if (!a1) { Serial.println(F("usage: fan 1|0")); return; }
    digitalWrite(PIN_FAN, atoi(a1) ? HIGH : LOW);
    Serial.print(F("fan ")); Serial.println(atoi(a1) ? F("on") : F("off"));
    return;
  }

  if (!strcmp(cmd, "selftest")) { cmdSelftest(); return; }

  Serial.print(F("unknown command: ")); Serial.println(cmd);
}

// ------------------------------------------------------------------ main --
void setup() {
  Serial.begin(BAUD);
  for (uint8_t i = 0; i < N_SLOTS; i++) {
    pinMode(axes[i].step, OUTPUT); digitalWrite(axes[i].step, LOW);
    pinMode(axes[i].dir,  OUTPUT); digitalWrite(axes[i].dir,  LOW);
    pinMode(axes[i].en,   OUTPUT); digitalWrite(axes[i].en,   EN_OFF);
    if (axes[i].minEs >= 0) pinMode(axes[i].minEs, INPUT_PULLUP);
    if (axes[i].maxEs >= 0) pinMode(axes[i].maxEs, INPUT_PULLUP);
  }
  pinMode(PIN_HOTWIRE, OUTPUT); digitalWrite(PIN_HOTWIRE, LOW);
  pinMode(PIN_FAN,     OUTPUT); digitalWrite(PIN_FAN,     LOW);

  lastLineMs = millis();
  Serial.println();
  Serial.print(F("foamcut hwtest on ")); Serial.println(F(BOARD_NAME));
  Serial.println(F("type ? for help"));
  printPinMap();
}

void loop() {
  static char buf[64];
  static uint8_t len = 0;

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      buf[len] = 0;
      lastLineMs = millis();
      handle(buf);
      len = 0;
      Serial.println(F("ok"));
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = c;
    }
  }

  // dead-man: never leave the wire hot without a live console
  if (hotwirePwm && (millis() - lastLineMs) > HOTWIRE_TIMEOUT_MS) {
    Serial.println(F("! hotwire dead-man timeout, switching off"));
    setHotwire(0);
  }
}
