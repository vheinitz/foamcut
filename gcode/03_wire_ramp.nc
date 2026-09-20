; 03 - hot wire power ramp, no motion.
;
; Run this with the wire strung and tensioned but with nothing to cut, and
; watch the wire (and an ammeter, if you have one). Find the lowest S value
; that melts foam without glowing red - that is your working setting.
;
; With $30=255 the S value is the PWM count directly: S128 = 50 % duty.
G21
G90
M3 S32
G4 P5
M3 S64
G4 P5
M3 S96
G4 P5
M3 S128
G4 P5
M3 S160
G4 P5
M5
M2
