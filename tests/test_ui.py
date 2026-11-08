"""Unit tests for the terminal UI (ui.py)."""

from __future__ import annotations

import os
import sys
from typing import Any, Callable

import pytest

import ui as ui_module
from data_loader import Flashcard
from quiz_engine import CardStats, SessionStats
from ui import EXIT_WORDS, QuizExit, QuizUI, format_table

GREEN = "\033[32m"
RED = "\033[31m"


def make_ui(
    answers: list[str] | None = None,
    use_color: bool | None = False,
    raise_on_input: BaseException | None = None,
) -> tuple[QuizUI, list[str], list[str]]:
    """Build a QuizUI with scripted input; return (ui, output lines, prompts)."""
    queue = list(answers or [])
    out: list[str] = []
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        if raise_on_input is not None:
            raise raise_on_input
        return queue.pop(0)

    def fake_print(*args: Any, **kwargs: Any) -> None:
        out.append(" ".join(str(a) for a in args))

    return QuizUI(fake_input, fake_print, use_color), out, prompts


@pytest.fixture
def card() -> Flashcard:
    """A simple card."""
    return Flashcard("Capital of France?", "Paris")


@pytest.fixture
def no_system(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub os.system so enabling colour never spawns a shell."""
    calls: list[str] = []

    def fake_system(command: str) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr("os.system", fake_system)
    return calls


# -- colour ---------------------------------------------------------------


def test_feedback_has_ansi_colours_when_enabled(
    no_system: list[str],
) -> None:
    """Green for correct and red for incorrect only when use_color=True."""
    ui, out, _ = make_ui(use_color=True)

    ui.show_feedback(True, "Paris")
    ui.show_feedback(False, "Paris")

    assert out[0].startswith(GREEN) and "Correct!" in out[0]
    assert out[1].startswith(RED) and "Incorrect. Expected: Paris" in out[1]
    assert out[0].count("\033[0m") == 1


def test_feedback_is_plain_when_colour_disabled() -> None:
    """No escape codes at all when use_color=False."""
    ui, out, _ = make_ui(use_color=False)

    ui.show_feedback(True, "Paris")
    ui.show_feedback(False, "Paris")

    assert all("\033" not in line for line in out)
    assert out[0].startswith("Correct!")
    assert out[1].startswith("Incorrect. Expected: Paris")


def test_feedback_reveals_expected_answer_only_when_wrong() -> None:
    """The right answer is shown after a miss but not after a hit."""
    ui, out, _ = make_ui()

    ui.show_feedback(True, "Paris")
    ui.show_feedback(False, "Paris")

    assert "Paris" not in out[0]
    assert "Paris" in out[1]


def test_colour_enabling_prepares_the_console(no_system: list[str]) -> None:
    """Enabling colour on Windows nudges the console into VT mode."""
    make_ui(use_color=True)

    assert no_system == ([""] if os.name == "nt" else [])


def test_no_color_env_disables_auto_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    """NO_COLOR wins even on a real terminal."""
    monkeypatch.setattr(ui_module, "_stdout_is_tty", lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")
    ui, out, _ = make_ui(use_color=None)

    ui.show_feedback(True, "x")

    assert "\033" not in out[0]


def test_non_tty_disables_auto_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    """Piped output (not a TTY) gets no colour."""
    monkeypatch.setattr(ui_module, "_stdout_is_tty", lambda: False)
    ui, out, _ = make_ui(use_color=None)

    ui.show_feedback(False, "x")

    assert "\033" not in out[0]


def test_tty_without_no_color_enables_auto_colour(
    monkeypatch: pytest.MonkeyPatch, no_system: list[str]
) -> None:
    """On a terminal and without NO_COLOR, auto mode turns colour on."""
    monkeypatch.setattr(ui_module, "_stdout_is_tty", lambda: True)
    ui, out, _ = make_ui(use_color=None)

    ui.show_feedback(True, "x")

    assert out[0].startswith(GREEN)


def test_explicit_colour_overrides_no_color_env(
    monkeypatch: pytest.MonkeyPatch, no_system: list[str]
) -> None:
    """use_color=True is an explicit choice that beats NO_COLOR."""
    monkeypatch.setenv("NO_COLOR", "1")
    ui, out, _ = make_ui(use_color=True)

    ui.show_feedback(True, "x")

    assert out[0].startswith(GREEN)


def test_stdout_is_tty_reflects_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """_stdout_is_tty uses isatty and survives odd streams."""

    class Tty:
        def isatty(self) -> bool:
            return True

    class Broken:
        def isatty(self) -> bool:
            raise ValueError("closed file")

    monkeypatch.setattr(sys, "stdout", Tty())
    assert ui_module._stdout_is_tty() is True
    monkeypatch.setattr(sys, "stdout", Broken())
    assert ui_module._stdout_is_tty() is False
    monkeypatch.setattr(sys, "stdout", object())
    assert ui_module._stdout_is_tty() is False


# -- ask / exit words -------------------------------------------------------


def test_ask_prints_numbered_question_and_returns_answer(card: Flashcard) -> None:
    """ask shows 'Q<n>: front', prompts, and returns the raw answer."""
    ui, out, prompts = make_ui(["  paris  "])

    answer = ui.ask(card, 3)

    assert out == ["Q3: Capital of France?"]
    assert prompts == ["Your answer: "]
    assert answer == "  paris  "


@pytest.mark.parametrize(
    "word", ["exit", "quit", "EXIT", "Quit", "  exit  ", "\tQUIT\n"]
)
def test_exit_words_raise_quit_exit(card: Flashcard, word: str) -> None:
    """exit/quit in any case, padded with whitespace, leave the quiz."""
    ui, _, _ = make_ui([word])

    with pytest.raises(QuizExit):
        ui.ask(card, 1)


def test_exit_words_constant() -> None:
    """EXIT_WORDS contains exactly exit and quit."""
    assert EXIT_WORDS == frozenset({"exit", "quit"})


@pytest.mark.parametrize("answer", ["exiting", "quit it", "ex it", "", "quit!"])
def test_near_miss_words_are_answers_not_exit(card: Flashcard, answer: str) -> None:
    """Only the exact exit words quit; similar text is just an answer."""
    ui, _, _ = make_ui([answer])

    assert ui.ask(card, 1) == answer


@pytest.mark.parametrize("word", ["exit", "quit"])
def test_exit_word_is_scored_when_it_is_the_expected_answer(word: str) -> None:
    """Bug fix: a card whose answer is 'exit'/'quit' accepts it as an answer."""
    tricky = Flashcard("Which keyword leaves a loop or program?", word)
    ui, _, _ = make_ui([word.upper()])

    assert ui.ask(tricky, 1) == word.upper()


def test_exit_word_matching_answer_uses_same_normalisation() -> None:
    """The expected-answer check ignores case and extra whitespace."""
    tricky = Flashcard("Which command stops the shell?", "  Exit ")
    ui, _, _ = make_ui(["  eXiT"])

    assert ui.ask(tricky, 1) == "  eXiT"


def test_exit_word_still_quits_when_it_is_not_the_expected_answer() -> None:
    """On a card whose answer is 'quit', typing 'exit' still leaves the quiz."""
    tricky = Flashcard("Which command stops the shell?", "quit")
    ui, _, _ = make_ui(["exit"])

    with pytest.raises(QuizExit):
        ui.ask(tricky, 1)


@pytest.mark.parametrize("error", [KeyboardInterrupt(), EOFError()])
def test_ctrl_c_and_eof_raise_quit_exit(card: Flashcard, error: BaseException) -> None:
    """Ctrl+C and end of input become QuizExit, keeping the cause."""
    ui, out, _ = make_ui(raise_on_input=error)

    with pytest.raises(QuizExit) as info:
        ui.ask(card, 1)

    assert info.value.__cause__ is error
    assert out[-1] == ""  # a newline is printed so the shell prompt is tidy


# -- welcome / goodbye / warning ------------------------------------------


def test_welcome_shows_mode_and_deck_size() -> None:
    """The greeting names the mode and card count and explains how to exit."""
    ui, out, _ = make_ui()

    ui.show_welcome(7, "adaptive")

    text = "\n".join(out)
    assert "Flashcard Quizzer" in text
    assert "Mode: adaptive | Cards: 7" in text
    assert "exit" in text and "quit" in text


def test_goodbye_message() -> None:
    """Quitting early prints a short notice."""
    ui, out, _ = make_ui()

    ui.show_goodbye()

    assert "Quiz stopped early." in out[0]


def test_warning_goes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """Warnings are written to stderr with a Warning: prefix."""
    ui, out, _ = make_ui()

    ui.show_warning("careful")

    captured = capsys.readouterr()
    assert captured.err == "Warning: careful\n"
    assert captured.out == ""
    assert out == []


# -- summary ----------------------------------------------------------------


def _stats(
    total: int, correct: int, missed: tuple[str, ...], per_card: dict[str, CardStats]
) -> SessionStats:
    return SessionStats(total, correct, missed, per_card)


def test_summary_table_content() -> None:
    """The summary lists totals, accuracy with one decimal and missed terms."""
    stats = _stats(3, 2, ("Capital of Spain?",), {"Capital of Spain?": CardStats(1, 0)})
    ui, out, _ = make_ui()

    ui.show_summary(stats)

    text = "\n".join(out)
    assert "=== Session Summary ===" in text
    assert "| Total Questions | 3     |" in text
    assert "| Correct         | 2     |" in text
    assert "| Accuracy %      | 66.7  |" in text
    assert "Missed terms:" in text
    assert "  - Capital of Spain?" in text
    assert "Per-card breakdown" not in text


def test_summary_detailed_adds_per_card_table() -> None:
    """detailed=True appends attempts/correct per card."""
    stats = _stats(
        3,
        1,
        ("B",),
        {"A": CardStats(1, 1), "B": CardStats(2, 0)},
    )
    ui, out, _ = make_ui()

    ui.show_summary(stats, detailed=True)

    text = "\n".join(out)
    assert "Per-card breakdown:" in text
    assert "| Card | Attempts | Correct |" in text
    assert "| A    | 1        | 1       |" in text
    assert "| B    | 2        | 0       |" in text


def test_summary_perfect_score_message() -> None:
    """A flawless session says so."""
    stats = _stats(2, 2, (), {"A": CardStats(1, 1), "B": CardStats(1, 1)})
    ui, out, _ = make_ui()

    ui.show_summary(stats)

    text = "\n".join(out)
    assert "perfect" in text
    assert "100.0" in text


def test_summary_empty_session_message() -> None:
    """With no questions answered the summary shows zeros and no 'perfect'."""
    ui, out, _ = make_ui()

    ui.show_summary(SessionStats(), detailed=True)

    text = "\n".join(out)
    assert "Missed terms: none" in text
    assert "perfect" not in text
    assert "0.0" in text
    assert "Per-card breakdown" not in text


def test_summary_truncates_long_fronts_in_per_card_table() -> None:
    """Fronts longer than 48 characters are cut with an ellipsis."""
    long_front = "x" * 100
    stats = _stats(1, 0, (long_front,), {long_front: CardStats(1, 0)})
    ui, out, _ = make_ui()

    ui.show_summary(stats, detailed=True)

    table_rows = [line for line in out if line.startswith("| x")]
    assert len(table_rows) == 1
    assert ("x" * 45 + "...") in table_rows[0]
    assert "x" * 46 not in table_rows[0]


def test_shorten_boundaries() -> None:
    """_shorten leaves exact-width text alone and truncates longer text."""
    exact = "a" * 48
    assert ui_module._shorten(exact) == exact
    cut = ui_module._shorten("a" * 49)
    assert len(cut) == 48 and cut.endswith("...")
    assert ui_module._shorten("abcdef", 5) == "ab..."


# -- format_table -----------------------------------------------------------


def test_format_table_alignment() -> None:
    """Columns are padded to the widest cell and borders match line length."""
    lines = format_table(["Name", "N"], [["alpha", "1"], ["b", "22"]])

    assert lines == [
        "+-------+----+",
        "| Name  | N  |",
        "+-------+----+",
        "| alpha | 1  |",
        "| b     | 22 |",
        "+-------+----+",
    ]
    assert len({len(line) for line in lines}) == 1


def test_format_table_without_rows() -> None:
    """A table with only headers still renders borders."""
    lines = format_table(["A", "B"], [])

    assert lines == ["+---+---+", "| A | B |", "+---+---+", "+---+---+"]


def test_format_table_header_wider_than_cells() -> None:
    """The header width wins when it is wider than every cell."""
    lines = format_table(["Heading"], [["x"]])

    assert lines[3] == "| x       |"


def test_default_input_and_print_are_the_builtins() -> None:
    """With no injection, the UI falls back to the builtins."""
    ui = QuizUI(use_color=False)
    default: Callable[..., Any] = ui._input

    assert default is input
