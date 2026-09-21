"""Load a Qt Designer file onto a widget. The .ui files under ui/ hold the
static layout (edit them in Qt Designer); pages add the dynamic parts -
forms generated from field catalogues, drawing canvases, jog pads - into
layouts named there for that purpose."""
from __future__ import annotations

from pathlib import Path

from PyQt6 import uic

UI_DIR = Path(__file__).resolve().parent / "ui"


def load_ui(name: str, widget) -> None:
    uic.loadUi(str(UI_DIR / f"{name}.ui"), widget)
