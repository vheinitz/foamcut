; 04 - steps per mm calibration.
;
; Mark each carriage, run this file, then measure the actual travel with a
; steel rule or a caliper. Correct the setting with
;
;     new $10x = old $10x * commanded / measured
;
; $100=X  $101=Y  $102=U  $103=V
;
; The wire stays cold: this is a motion test only.
G21
G90
G94
M5
G1 F600
G91 ; relative, so the file works from wherever the machine is parked
G1 X100.000
G4 P2
G1 X-100.000
G4 P2
G1 Y100.000
G4 P2
G1 Y-100.000
G4 P2
G1 U100.000
G4 P2
G1 U-100.000
G4 P2
G1 V100.000
G4 P2
G1 V-100.000
G90
M2
