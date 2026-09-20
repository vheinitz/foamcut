#include <Arduino.h>

// GT2560 - alle 5 Slots (RAMPS-kompatibel, Arduino-Mega-Pinnummern)
// Reihenfolge: X, Y, Z, E0, E1
const int STEP_PIN[5] = {54, 60, 46, 26, 36};
const int DIR_PIN[5]  = {55, 61, 48, 28, 34};
const int EN_PIN[5]   = {38, 56, 62, 24, 30};

const long STEPS = 50000;     // Schritte pro Richtung
const int  STEP_US = 400;     // halbe Periodendauer in us

void setup() {
  for (int i = 0; i < 5; i++) {
    pinMode(STEP_PIN[i], OUTPUT);
    pinMode(DIR_PIN[i], OUTPUT);
    pinMode(EN_PIN[i], OUTPUT);
    digitalWrite(EN_PIN[i], LOW);   // Treiber aktivieren (active low)
  }
}

void loop() {
  for (int i = 0; i < 5; i++) digitalWrite(DIR_PIN[i], HIGH);
  for (long s = 0; s < STEPS; s++) {
    for (int i = 0; i < 5; i++) digitalWrite(STEP_PIN[i], HIGH);
    delayMicroseconds(STEP_US);
    for (int i = 0; i < 5; i++) digitalWrite(STEP_PIN[i], LOW);
    delayMicroseconds(STEP_US);
  }

  delay(2000);

  for (int i = 0; i < 5; i++) digitalWrite(DIR_PIN[i], LOW);
  for (long s = 0; s < STEPS; s++) {
    for (int i = 0; i < 5; i++) digitalWrite(STEP_PIN[i], HIGH);
    delayMicroseconds(STEP_US);
    for (int i = 0; i < 5; i++) digitalWrite(STEP_PIN[i], LOW);
    delayMicroseconds(STEP_US);
  }

  delay(2000);
}
