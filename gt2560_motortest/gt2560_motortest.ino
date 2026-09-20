/*
 * GT2560 Rev.A / Rev.A+ — 4-Motoren-Test (interaktiv)
 * ====================================================
 *
 * Einfacher Test, um die vier Motoren eines Geeetech GT2560 (ATmega2560)
 * einzeln zu pruefen. Kein Motion-Planner, keine Libraries — STEP/DIR/EN
 * wird nur von Hand getoggelt.
 *
 * WICHTIG — das GT2560 ist NICHT RAMPS-pinkompatibel!
 * Ein RAMPS-Sketch (X = D54/D55/D38) toggelt Pins, die am GT2560 gar nicht
 * mit dem Treiber verbunden sind, die Motoren bewegen sich also nie.
 * Die Zahlen unten stammen aus Marlin pins_GT2560_REV_A.h /
 * pins_GT2560_REV_A_PLUS.h und sind fuer Rev.A und Rev.A+ identisch.
 *
 * Mikrostepping: Bei A4988/DRV8825 (MS1/MS2/MS3) und TMC2209 (MS1/MS2)
 * wird das Mikrostepping ueber die Jumper UNTER dem jeweiligen
 * Treiber-Steckplatz eingestellt, nicht per Software. Der Befehl 'm' gibt
 * dem Sketch nur die Jumper-Stellung an, damit eine Umdrehung
 * = 200 * Mikrostepping Schritte ergibt. A4988 max. 1/16, TMC2209 mit
 * MS-Jumpern 1/8, 1/16, 1/32 oder 1/64.
 *
 * Konsole: 115200 Baud. Ein Befehl pro Parameter, mehrere Befehle pro Zeile
 * mit ';' getrennt. '?' zeigt die aktuellen Parameter, 'h' die Hilfe.
 */

// ------------------------------------------------------------------ Pins --
// Arduino-Mega-Pinnummern. Reihenfolge = Beschriftung auf dem Board:
// X, Y, Z, E0, E1.
const uint8_t STEP_PIN[5] = {25, 31, 37, 43, 49};
const uint8_t DIR_PIN[5]  = {23, 33, 39, 45, 47};
const uint8_t EN_PIN[5]   = {27, 29, 35, 41, 48};

// Achsen-Buchstaben, in derselben Reihenfolge wie die Pin-Tabellen oben.
// X/Y/Z/U sind die vier Motoren, 'E' ist der Reserve-Slot E1 (praktisch,
// wenn z.B. der E0-Steckplatz kaputt ist).
// Falls Deine Maschine die Achsen X/Y/U/V nennt, aendere hier
// 'Z' -> 'U' und 'U' -> 'V'.
const char   AXIS_NAME[5] = {'X', 'Y', 'Z', 'U', 'E'};
const char  *SLOT_NAME[5] = {"X", "Y", "Z", "E0", "E1"};

const uint8_t N_AXES = 5;

// ---------------------------------------------------------------- Treiber --
// A4988 / DRV8825: Enable ist aktiv LOW.
const uint8_t EN_ON  = LOW;
const uint8_t EN_OFF = HIGH;

// ----------------------------------------------------------- Einstellungen --
const uint16_t MOTOR_STEPS_PER_REV = 200;  // 1,8-Grad-NEMA17; bei 0,9-Grad 400
const uint16_t MIN_PERIOD_US = 20;         // praktischer Boden: darunter dominiert der digitalWrite-Overhead
const uint16_t RAMP_STEPS = 500;           // Anlauf-Rampe: max. Schritte bis zur Zielgeschwindigkeit
const uint16_t RAMP_START_HALF_US = 2000;  // Rampe startet langsam (Halbperiode in us)

uint16_t microstep  = 1;        // Jumper-Einstellung: 1, 2, 4, 8, 16 (32 = DRV8825)
uint16_t periodUs   = 2000;     // volle Schrittperiode (HIGH+LOW) in µs
uint8_t  curAxis    = 0;        // 0..3, aktuell ausgewaehlte Achse
bool     driversOn  = false;

// ---------------------------------------------------------------- Helfer --
static int findAxis(char c) {
  c = toupper(c);
  for (uint8_t i = 0; i < N_AXES; i++) if (AXIS_NAME[i] == c) return i;
  if (c >= '0' && c <= '4') return c - '0';   // auch Slot-Nummer 0..4 erlaubt
  return -1;
}

static void enableDrivers(bool on) {
  driversOn = on;
  for (uint8_t i = 0; i < N_AXES; i++) digitalWrite(EN_PIN[i], on ? EN_ON : EN_OFF);
  Serial.print(F("Treiber "));
  Serial.println(on ? F("AN (Motoren fest)") : F("aus (Wellen drehbar)"));
}

// delayMicroseconds() ist auf AVR nur bis 16383 us zuverlaessig.
// Fuer grosse Perioden (Zeitlupentempo) in ms + Rest aufteilen.
static void delayStepUs(uint16_t us) {
  if (us > 16383) {
    delay(us / 1000);
    delayMicroseconds(us % 1000);
  } else {
    delayMicroseconds(us);
  }
}

// Anlauf-Rampe: der Motor startet langsam und beschleunigt innerhalb von
// <rampLen> Schritten auf die Ziel-Halbperiode. Ohne Rampe verschluckt sich
// ein Treiber/Motor beim Kaltstart an schnellen Schrittfolgen (Stall).
static uint16_t rampHalf(uint16_t targetHalf, long s, long rampLen) {
  if (targetHalf < RAMP_START_HALF_US && s < rampLen && rampLen > 0) {
    int32_t diff = (int32_t)targetHalf - RAMP_START_HALF_US;   // negativ
    return (uint16_t)(RAMP_START_HALF_US + (diff * (int32_t)s) / rampLen);
  }
  return targetHalf;
}

// Faehrt eine Achse um <steps> Schritte. forward = Drehrichtung.
static void jog(uint8_t idx, long steps, bool forward) {
  uint16_t half = periodUs >> 1;
  long rampLen = steps / 4;
  if (rampLen > RAMP_STEPS) rampLen = RAMP_STEPS;
  digitalWrite(DIR_PIN[idx], forward ? HIGH : LOW);
  delayMicroseconds(20);               // DIR-Setupzeit fuer A4988/DRV8825
  for (long s = 0; s < steps; s++) {
    uint16_t h = rampHalf(half, s, rampLen);
    digitalWrite(STEP_PIN[idx], HIGH);
    delayStepUs(h);
    digitalWrite(STEP_PIN[idx], LOW);
    delayStepUs(h);
  }
}

// Alle vier Achsen gleichzeitig (Lockstep) — der Nachweis, dass vier Achsen
// parallel gefahren werden koennen, was ein 3-Achsen-Board nicht kann.
static void jogAll(long steps, bool forward) {
  uint16_t half = periodUs >> 1;
  long rampLen = steps / 4;
  if (rampLen > RAMP_STEPS) rampLen = RAMP_STEPS;
  for (uint8_t i = 0; i < N_AXES; i++) digitalWrite(DIR_PIN[i], forward ? HIGH : LOW);
  delayMicroseconds(20);
  for (long s = 0; s < steps; s++) {
    uint16_t h = rampHalf(half, s, rampLen);
    for (uint8_t i = 0; i < N_AXES; i++) digitalWrite(STEP_PIN[i], HIGH);
    delayStepUs(h);
    for (uint8_t i = 0; i < N_AXES; i++) digitalWrite(STEP_PIN[i], LOW);
    delayStepUs(h);
  }
}

// ---------------------------------------------------------------- Ausgabe --
static void printPinMap() {
  Serial.println(F("Achse  Slot  STEP  DIR  EN"));
  for (uint8_t i = 0; i < N_AXES; i++) {
    Serial.print(F("  "));  Serial.print(AXIS_NAME[i]);
    Serial.print(F("    ")); Serial.print(SLOT_NAME[i]);
    Serial.print(F("    D")); Serial.print(STEP_PIN[i]);
    Serial.print(F("  D"));  Serial.print(DIR_PIN[i]);
    Serial.print(F("  D"));  Serial.println(EN_PIN[i]);
  }
}

static void printStatus() {
  Serial.print(F("Achse=")); Serial.print(AXIS_NAME[curAxis]);
  Serial.print(F(" (Slot ")); Serial.print(SLOT_NAME[curAxis]); Serial.print(F(")"));
  Serial.print(F("  ustep=1/")); Serial.print(microstep);
  Serial.print(F("  Schritte/Move=")); Serial.print((long)MOTOR_STEPS_PER_REV * microstep);
  Serial.print(F("  Periode=")); Serial.print(periodUs); Serial.print(F("us"));
  Serial.print(F("  Treiber=")); Serial.println(driversOn ? F("an") : F("aus"));
}

static void printHelp() {
  Serial.println(F(
    "Befehle (je ein Parameter, mehrere mit ';' trennbar):\r\n"
    "  a <x|y|z|u|e>   Achse auswaehlen (e = Reserve-Slot E1)\r\n"
    "  + [steps]     vorwaerts, Default 200*ustep = 1 Umdrehung\r\n"
    "  - [steps]     rueckwaerts, Default 200*ustep\r\n"
    "  m <1|2|4|8|16|32|64>  Mikrostepping (Jumper-Stellung angeben)\r\n"
    "  u <us>        Schrittperiode in µs (min 20, mit Anlauf-Rampe)\r\n"
    "  b [steps]     aktuelle Achse hin und her\r\n"
    "  t [steps]     alle Achsen nacheinander\r\n"
    "  g [steps]     alle Achsen gleichzeitig\r\n"
    "  e <1|0>       Treiber an / aus\r\n"
    "  ?             aktuelle Parameter\r\n"
    "  h             diese Hilfe\r\n"
    "Beispiel:  a x; m 16; +; -"));
}

// ---------------------------------------------------------------- Befehle --
static void runCommand(char *seg) {
  while (*seg == ' ') seg++;
  if (!*seg) return;

  char *cmd = strtok(seg, " ");
  char *arg = strtok(NULL, " ");

  if (cmd[1] != 0) { Serial.print(F("unbekannter Befehl: ")); Serial.println(cmd); return; }
  char c = cmd[0];

  if (c == '?') { printStatus(); return; }
  if (c == 'h') { printHelp(); return; }

  if (c == 'a') {
    if (!arg) { Serial.println(F("usage: a <x|y|z|u|e>")); return; }
    int idx = findAxis(arg[0]);
    if (idx < 0) { Serial.println(F("unbekannte Achse")); return; }
    curAxis = (uint8_t)idx;
    Serial.print(F("Achse ")); Serial.print(AXIS_NAME[curAxis]);
    Serial.print(F(" (Slot ")); Serial.print(SLOT_NAME[curAxis]); Serial.println(F(") ausgewaehlt"));
    return;
  }

  if (c == 'm') {
    if (!arg) { Serial.println(F("usage: m <1|2|4|8|16|32|64>")); return; }
    long v = atol(arg);
    if (v != 1 && v != 2 && v != 4 && v != 8 && v != 16 && v != 32 && v != 64) {
      Serial.println(F("nur 1, 2, 4, 8, 16, 32, 64"));
      return;
    }
    microstep = (uint16_t)v;
    Serial.print(F("Mikrostepping=1/")); Serial.print(microstep);
    Serial.print(F(" -> ")); Serial.print((long)MOTOR_STEPS_PER_REV * microstep);
    Serial.println(F(" Schritte/Umdrehung"));
    return;
  }

  if (c == 'u') {
    if (!arg) { Serial.println(F("usage: u <periode_us>")); return; }
    long v = atol(arg);
    if (v < MIN_PERIOD_US) { Serial.print(F("zu schnell, min ")); Serial.println(MIN_PERIOD_US); return; }
    if (v > 65535) v = 65535;
    periodUs = (uint16_t)v;
    Serial.print(F("Schrittperiode=")); Serial.print(periodUs); Serial.println(F("us"));
    if (periodUs < 200) Serial.println(F("! sehr schnell — ohne genug Treiberstrom stallen die Motoren beim Anlauf"));
    return;
  }

  if (c == 'e') {
    if (!arg) { Serial.println(F("usage: e <1|0>")); return; }
    enableDrivers(atoi(arg) != 0);
    return;
  }

  if (c == '+' || c == '-') {
    long n = (long)MOTOR_STEPS_PER_REV * microstep;   // Default: 1 Umdrehung
    if (arg) {
      n = atol(arg);
      if (n <= 0) { Serial.println(F("Schritte muessen > 0 sein")); return; }
    }
    if (!driversOn) enableDrivers(true);
    bool fwd = (c == '+');
    Serial.print(F("Achse ")); Serial.print(AXIS_NAME[curAxis]);
    Serial.print(fwd ? F(" +") : F(" -"));
    Serial.print(n); Serial.println(F(" Schritte"));
    jog(curAxis, n, fwd);
    return;
  }

  if (c == 'b' || c == 't' || c == 'g') {
    long n = (long)MOTOR_STEPS_PER_REV * microstep;
    if (arg) {
      n = atol(arg);
      if (n <= 0) { Serial.println(F("Schritte muessen > 0 sein")); return; }
    }
    if (!driversOn) enableDrivers(true);
    if (c == 'b') {
      Serial.print(F("Achse ")); Serial.print(AXIS_NAME[curAxis]);
      Serial.print(F(" hin und her, ")); Serial.print(n); Serial.println(F(" Schritte"));
      jog(curAxis, n, true);
      delay(800);
      jog(curAxis, n, false);
    } else if (c == 't') {
      Serial.println(F("alle Achsen nacheinander:"));
      for (uint8_t i = 0; i < N_AXES; i++) {
        Serial.print(F("  ")); Serial.print(AXIS_NAME[i]); Serial.print(F(" +"));
        jog(i, n, true);
        delay(500);
        Serial.print(F(" -"));
        jog(i, n, false);
        delay(500);
        Serial.println();
      }
    } else {
      Serial.println(F("alle Achsen gleichzeitig: + dann -"));
      jogAll(n, true);
      delay(800);
      jogAll(n, false);
    }
    Serial.println(F("fertig"));
    return;
  }

  Serial.print(F("unbekannter Befehl: ")); Serial.println(cmd);
}

// Eine Zeile an ';' in einzelne Befehle zerlegen und nacheinander ausfuehren.
static void handle(char *line) {
  char *seg = line;
  while (seg && *seg) {
    char *end = strchr(seg, ';');
    if (end) *end = 0;
    while (*seg == ' ') seg++;
    if (*seg) runCommand(seg);
    seg = end ? end + 1 : NULL;
  }
}

// ------------------------------------------------------------------ main --
void setup() {
  Serial.begin(115200);
  delay(50);                              // Reset-Garbage vom USB-Wandler einsammeln
  while (Serial.available()) Serial.read();

  for (uint8_t i = 0; i < N_AXES; i++) {
    pinMode(STEP_PIN[i], OUTPUT); digitalWrite(STEP_PIN[i], LOW);
    pinMode(DIR_PIN[i],  OUTPUT); digitalWrite(DIR_PIN[i],  LOW);
    pinMode(EN_PIN[i],   OUTPUT); digitalWrite(EN_PIN[i],   EN_OFF);
  }

  Serial.println();
  Serial.println(F("GT2560 Rev.A/Rev.A+ — 4-Motoren-Test"));
  Serial.println(F("? = Parameter, h = Hilfe"));
  printPinMap();
  printStatus();
  Serial.println(F("Bereit. Beispiel: a x; m 16; +; -"));
  Serial.print(F("> "));
}

void loop() {
  static char buf[64];
  static uint8_t len = 0;
  static uint32_t lastCharMs = 0;
  static bool skipLF = false;

  while (Serial.available()) {
    char c = Serial.read();
    lastCharMs = millis();

    if (c == '\n') {                       // Zeilenende LF (auch nach CR)
      if (skipLF) { skipLF = false; continue; }
      if (len > 0) { buf[len] = 0; handle(buf); len = 0; }
      Serial.print(F("> "));
    } else if (c == '\r') {                // Zeilenende CR
      if (len > 0) { buf[len] = 0; handle(buf); len = 0; }
      Serial.print(F("\r\n> "));
      skipLF = true;
    } else {
      skipLF = false;
      if (c == 8 || c == 127) {            // Backspace
        if (len > 0) { len--; Serial.print(F("\b \b")); }
      } else if (len < sizeof(buf) - 1) {
        buf[len++] = c;
        Serial.print(c);                   // Echo, damit man sieht was getippt wurde
      }
    }
  }

  // Fallback fuer Monitore ohne Zeilenende ("No line ending"):
  // kurze Tipppause beendet die Zeile auch ohne Enter.
  if (len > 0 && (millis() - lastCharMs) > 1000) {
    buf[len] = 0;
    Serial.println();
    handle(buf);
    len = 0;
    Serial.print(F("> "));
  }
}
