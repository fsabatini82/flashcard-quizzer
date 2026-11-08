"""Terminal user interface for the quizzer.

All console input and output lives here. Input and output functions are
injectable so the UI can be tested without a terminal.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Sequence

from data_loader import Flashcard
from quiz_engine import SessionStats, normalize_answer

EXIT_WORDS = frozenset({"exit", "quit"})
_GREEN = "\033[32m"
_RED = "\033[31m"
_RESET = "\033[0m"
_MAX_CELL = 48


class QuizExit(Exception):
    """Raised when the user asks to leave the quiz early."""


def _shorten(text: str, width: int = _MAX_CELL) -> str:
    """Truncate text to ``width`` characters, adding an ellipsis if cut."""
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


def format_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    """Render an aligned ASCII table.

    Args:
        headers: Column titles.
        rows: Table rows; each row has one cell per header.

    Returns:
        The table as a list of lines.
    """
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    border = "+-" + "-+-".join("-" * width for width in widths) + "-+"

    def line(cells: Sequence[str]) -> str:
        padded = (cell.ljust(width) for cell, width in zip(cells, widths))
        return "| " + " | ".join(padded) + " |"

    return [border, line(headers), border, *(line(row) for row in rows), border]


class QuizUI:
    """Console front-end: prompts, feedback and the results summary."""

    def __init__(
        self,
        input_fn: Callable[[str], str] | None = None,
        print_fn: Callable[..., None] | None = None,
        use_color: bool | None = None,
    ) -> None:
        """Create the UI.

        Args:
            input_fn: Function used to read a line, given a prompt. ``None``
                uses the builtin ``input``, looked up when the UI is created
                (so it can be patched).
            print_fn: Function used to print a line. ``None`` uses the
                builtin ``print``, looked up when the UI is created.
            use_color: Force colours on or off. ``None`` auto-detects: colours
                are off when ``NO_COLOR`` is set or stdout is not a terminal.
        """
        self._input: Callable[[str], str] = input_fn if input_fn is not None else input
        self._print: Callable[..., None] = print_fn if print_fn is not None else print
        if use_color is None:
            use_color = not os.environ.get("NO_COLOR") and _stdout_is_tty()
        self._use_color = use_color
        if self._use_color and os.name == "nt":
            # Calling the shell once switches the Windows console to VT mode.
            os.system("")

    def _paint(self, text: str, color: str) -> str:
        """Wrap text in an ANSI colour when colours are enabled."""
        if not self._use_color:
            return text
        return f"{color}{text}{_RESET}"

    def show_welcome(self, deck_size: int, mode_name: str) -> None:
        """Print the greeting.

        Args:
            deck_size: Number of cards in the deck.
            mode_name: Name of the active quiz mode.
        """
        self._print("=== Flashcard Quizzer ===")
        self._print(f"Mode: {mode_name} | Cards: {deck_size}")
        self._print("Type 'exit' or 'quit' (or press Ctrl+C) to stop early.\n")

    def ask(self, card: Flashcard, index: int) -> str:
        """Show a card and read the answer.

        Args:
            card: The card to ask.
            index: 1-based question number.

        Returns:
            The user's answer.

        Raises:
            QuizExit: On 'exit'/'quit', Ctrl+C or end of input. An exit word
                is scored as a normal answer when it is the card's expected
                answer (compared with :func:`normalize_answer`).
        """
        self._print(f"Q{index}: {card.front}")
        try:
            answer = self._input("Your answer: ")
        except (KeyboardInterrupt, EOFError) as exc:
            self._print("")
            raise QuizExit from exc
        normalized = normalize_answer(answer)
        if normalized in EXIT_WORDS and normalized != normalize_answer(card.back):
            raise QuizExit
        return answer

    def show_feedback(self, correct: bool, expected: str) -> None:
        """Show whether the last answer was right.

        Args:
            correct: Whether the answer was correct.
            expected: The expected answer, revealed when wrong.
        """
        if correct:
            self._print(self._paint("Correct!", _GREEN) + "\n")
        else:
            message = f"Incorrect. Expected: {expected}"
            self._print(self._paint(message, _RED) + "\n")

    def show_summary(self, stats: SessionStats, detailed: bool = False) -> None:
        """Print the session summary.

        Args:
            stats: Results to display.
            detailed: Also print the per-card breakdown table.
        """
        self._print("\n=== Session Summary ===")
        rows = [
            ["Total Questions", str(stats.total_questions)],
            ["Correct", str(stats.correct_count)],
            ["Accuracy %", f"{stats.accuracy_percent:.1f}"],
        ]
        for text in format_table(["Metric", "Value"], rows):
            self._print(text)
        if stats.missed_terms:
            self._print("\nMissed terms:")
            for term in stats.missed_terms:
                self._print(f"  - {term}")
        elif stats.total_questions:
            self._print("\nMissed terms: none - perfect!")
        else:
            self._print("\nMissed terms: none")
        if detailed and stats.per_card:
            self._print("\nPer-card breakdown:")
            card_rows = [
                [_shorten(front), str(item.attempts), str(item.correct)]
                for front, item in stats.per_card.items()
            ]
            for text in format_table(["Card", "Attempts", "Correct"], card_rows):
                self._print(text)

    def show_goodbye(self) -> None:
        """Announce that the quiz ended early."""
        self._print("\nQuiz stopped early.")

    def show_warning(self, message: str) -> None:
        """Print a warning line to stderr.

        Args:
            message: Text to show after the ``Warning:`` prefix.
        """
        print(f"Warning: {message}", file=sys.stderr)


def _stdout_is_tty() -> bool:
    """Return whether stdout is an interactive terminal."""
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False
