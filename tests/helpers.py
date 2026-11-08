"""Shared helpers for the test suite (fake stdin, deck writing)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence


class FakeStdin:
    """A minimal stdin replacement that feeds scripted lines to ``input()``.

    When the script is exhausted it either signals end-of-file (the default)
    or raises the exception given in ``then_raise``.
    """

    def __init__(
        self,
        lines: Sequence[str],
        then_raise: type[BaseException] | None = None,
    ) -> None:
        self._lines = list(lines)
        self._then_raise = then_raise
        self.reads = 0

    def readline(self, size: int = -1) -> str:
        """Return the next scripted line, or react to exhaustion."""
        self.reads += 1
        if self._lines:
            return self._lines.pop(0) + "\n"
        if self._then_raise is not None:
            raise self._then_raise()
        return ""


def write_deck(path: Path, data: Any) -> Path:
    """Write ``data`` as JSON to ``path`` and return the path."""
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def three_card_data() -> list[dict[str, str]]:
    """Return a raw three-card deck used by many tests."""
    return [
        {"front": "Capital of France?", "back": "Paris"},
        {"front": "Capital of Italy?", "back": "Rome"},
        {"front": "Capital of Spain?", "back": "Madrid"},
    ]
