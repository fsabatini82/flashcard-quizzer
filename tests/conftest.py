"""Shared pytest fixtures for the Flashcard Quizzer tests."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from data_loader import Flashcard
from tests.helpers import FakeStdin, three_card_data, write_deck


@pytest.fixture
def cards() -> list[Flashcard]:
    """Five distinct flashcards."""
    return [Flashcard(f"Q{i}", f"A{i}") for i in range(1, 6)]


@pytest.fixture
def deck_file(tmp_path: Path) -> Path:
    """A valid three-card deck stored in a temporary file."""
    return write_deck(tmp_path / "deck.json", three_card_data())


@pytest.fixture
def feed_input(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeStdin]:
    """Return a function that scripts what the user types on stdin.

    ``feed_input(["a", "b"])`` ends with end-of-file; pass
    ``then_raise=KeyboardInterrupt`` to simulate Ctrl+C after the lines.
    """

    def _feed(
        lines: list[str], then_raise: type[BaseException] | None = None
    ) -> FakeStdin:
        stdin = FakeStdin(lines, then_raise)
        monkeypatch.setattr("sys.stdin", stdin)
        return stdin

    return _feed


@pytest.fixture(autouse=True)
def _clean_color_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make colour auto-detection independent of the developer's shell."""
    monkeypatch.delenv("NO_COLOR", raising=False)
