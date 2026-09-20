; 05 - four axis synchronisation.
;
; Every move changes all four axes at once, with the two towers travelling
; different distances. If the controller drops an axis or serialises the
; moves, the towers arrive at different times and you see it immediately.
;
; Nothing here is cuttable geometry - it is a motion test. Wire stays cold.
G21
G90
G94
M5
G1 F400
G1 X0.000   Y0.000   U0.000   V0.000
G1 X40.000  Y10.000  U20.000  V30.000
G1 X10.000  Y40.000  U30.000  V5.000
G1 X40.000  Y40.000  U5.000   V40.000
G1 X0.000   Y0.000   U0.000   V0.000
M2
