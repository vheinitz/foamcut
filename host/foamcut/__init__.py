"""Host side tooling for the GT2560 XYUV hot wire foam cutter."""

__version__ = "0.1.0"

# Foam cutter axis letters, in the order grbl reports them.
#   X, Y = left tower (horizontal, vertical)
#   U, V = right tower (horizontal, vertical)
AXES = ("X", "Y", "U", "V")
