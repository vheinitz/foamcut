// Endschalter-Logger fuer die GT2560 Rev A+ (ATmega2560), Arduino IDE, Board "Arduino Mega 2560".
//
// Liest alle sechs Endstop-Stecker plus die beiden Ersatz-Eingaenge fuer V
// (EXP2 Pin 7 = D38, EXP2 Pin 5 = D40, siehe docs/gt2560_pinout.md) mit
// internem Pull-up und meldet jede Aenderung auf 115200 Baud:
//
//   X_MIN D22: LOW  (geschlossen nach GND)      <- Schalter verbindet S mit GND
//   X_MIN D22: HIGH (offen / Pull-up)           <- Schalter offen oder an +5V
//
// Damit sieht man je Schalter: an welchem Stecker er haengt, ob er Oeffner
// oder Schliesser ist, und ob er ueberhaupt nach GND schaltet. Alle 2 s
// kommt eine Zeile mit dem Gesamtzustand. Danach grbl wieder flashen
// (firmware/grbl5x/build.sh flash).

struct Input { const char* name; uint8_t pin; };

const Input INPUTS[] = {
  {"X_MIN", 22}, {"X_MAX", 24},
  {"Y_MIN", 26}, {"Y_MAX", 28},
  {"Z_MIN", 30}, {"Z_MAX", 32},   // Z-Steckplatz = Achse U
  {"EXP2_7 (V_MIN) D38", 38}, {"EXP2_5 (V_MAX) D40", 40},
};
const uint8_t N = sizeof(INPUTS) / sizeof(INPUTS[0]);
uint8_t last[N];
unsigned long lastSummary = 0;

static const char* describe(uint8_t v) {
  return v == LOW ? "LOW  (geschlossen nach GND)" : "HIGH (offen / Pull-up)";
}

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < N; i++) {
    pinMode(INPUTS[i].pin, INPUT_PULLUP);
    last[i] = 0xFF;
  }
  delay(200);
  Serial.println(F("endstop_test: Pull-up an, LOW = Schalter zieht nach GND"));
}

void summary() {
  Serial.print(F("Zustand:"));
  for (uint8_t i = 0; i < N; i++) {
    Serial.print(' ');
    Serial.print(INPUTS[i].name);
    Serial.print('=');
    Serial.print(digitalRead(INPUTS[i].pin) == LOW ? 'L' : 'H');
  }
  Serial.println();
}

void loop() {
  for (uint8_t i = 0; i < N; i++) {
    uint8_t v = digitalRead(INPUTS[i].pin);
    if (v != last[i]) {
      delay(5);                                  // entprellen
      if (digitalRead(INPUTS[i].pin) != v) continue;
      last[i] = v;
      Serial.print(millis() / 1000.0, 1);
      Serial.print(F(" s  "));
      Serial.print(INPUTS[i].name);
      Serial.print(F(" D"));
      Serial.print(INPUTS[i].pin);
      Serial.print(F(": "));
      Serial.println(describe(v));
    }
  }
  if (millis() - lastSummary > 2000) {
    lastSummary = millis();
    summary();
  }
}
