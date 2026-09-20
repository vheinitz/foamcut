"""What the UI remembers between sessions: last wing values, last program, geometry."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = Path("config/ui_state.json")


class UiState:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self.data: dict = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except (OSError, ValueError):
                self.data = {}

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")
        except OSError:
            pass
