"""End-to-end tests: real stack, scripted user, no real terminal."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

import main as main_module
from data_loader import load_flashcards
from main import build_parser, main, run_quiz
from quiz_engine import QuizSession, create_mode
from tests.helpers import FakeStdin, three_card_data, write_deck
from ui import QuizUI
from utils.exporter import ExportError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FeedInput = Callable[..., FakeStdin]


def run_cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    """Call main() and return (exit code, stdout, stderr)."""
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def asked_fronts(output: str) -> list[str]:
    """Extract the question texts from captured quiz output, in order."""
    return re.findall(r"^Q\d+: (.*)$", output, flags=re.MULTILINE)


# --------------------------------------------------------------------------
# The required full-session test
# --------------------------------------------------------------------------


def test_full_session(tmp_path: Path) -> None:
    """A user answers exactly 3 questions (2 right, 1 wrong) through the real stack."""
    deck = write_deck(tmp_path / "deck.json", three_card_data())
    answers = iter(["paris", "Milan", "  MADRID "])
    printed: list[str] = []

    def fake_input(prompt: str) -> str:
        return next(answers)

    def fake_print(*parts: Any, **kwargs: Any) -> None:
        printed.append(" ".join(str(part) for part in parts))

    cards = load_flashcards(deck)
    mode = create_mode("sequential", cards)
    session = QuizSession(mode)
    ui = QuizUI(fake_input, fake_print, use_color=False)

    run_quiz(session, ui)
    stats = session.stats()
    ui.show_summary(stats, detailed=True)

    assert stats.total_questions == 3
    assert stats.correct_count == 2
    assert stats.accuracy_percent == pytest.approx(66.7, abs=0.05)
    assert stats.missed_terms == ("Capital of Italy?",)
    assert [record.correct for record in session.history] == [True, False, True]

    text = "\n".join(printed)
    assert "Q1: Capital of France?" in text
    assert "Q3: Capital of Spain?" in text
    assert "Incorrect. Expected: Rome" in text
    assert "=== Session Summary ===" in text
    assert re.search(r"Total Questions \| 3\b", text)
    assert re.search(r"Correct\s+\| 2\b", text)
    assert "66.7" in text
    assert "  - Capital of Italy?" in text


def test_full_session_via_main(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same 3-question scenario through main(): stdout carries the summary."""
    feed_input(["Paris", "Milan", "madrid"])

    code, out, err = run_cli(capsys, "--file", str(deck_file))

    assert code == 0
    assert err == ""
    assert re.search(r"Total Questions \| 3\b", out)
    assert re.search(r"Correct\s+\| 2\b", out)
    assert "66.7" in out
    assert "Capital of Italy?" in out.split("Missed terms:")[1]


# --------------------------------------------------------------------------
# Sessions through main()
# --------------------------------------------------------------------------


def test_sequential_happy_path_exit_code_zero(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """All answers right in sequential mode: code 0, deck order, perfect score."""
    feed_input(["Paris", "Rome", "Madrid"])

    code, out, err = run_cli(capsys, "-f", str(deck_file))

    assert code == 0
    assert err == ""
    assert asked_fronts(out) == [c["front"] for c in three_card_data()]
    assert out.count("Correct!") == 3
    assert "perfect" in out
    assert "100.0" in out
    assert "Mode: sequential | Cards: 3" in out


def test_exit_mid_quiz_returns_zero_with_summary(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """Typing 'exit' ends the quiz gracefully and still prints the summary."""
    feed_input(["Paris", "exit"])

    code, out, err = run_cli(capsys, "-f", str(deck_file))

    assert code == 0
    assert "Quiz stopped early." in out
    assert "=== Session Summary ===" in out
    assert re.search(r"Total Questions \| 1\b", out)
    assert "Traceback" not in out + err


def test_quit_word_is_case_insensitive_end_to_end(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """'  QUIT ' at the first prompt ends with zero questions scored."""
    feed_input(["  QUIT "])

    code, out, _ = run_cli(capsys, "-f", str(deck_file))

    assert code == 0
    assert re.search(r"Total Questions \| 0\b", out)
    assert "Missed terms: none" in out


def test_end_of_input_is_handled_like_exit(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """EOF (Ctrl+D / closed pipe) ends the quiz with code 0 and a summary."""
    feed_input(["Paris"])  # then EOF

    code, out, err = run_cli(capsys, "-f", str(deck_file))

    assert code == 0
    assert "Quiz stopped early." in out
    assert re.search(r"Total Questions \| 1\b", out)
    assert "Traceback" not in out + err


def test_keyboard_interrupt_is_handled_like_exit(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ctrl+C ends the quiz with code 0, a summary and no traceback."""
    feed_input(["Paris", "wrong"], then_raise=KeyboardInterrupt)

    code, out, err = run_cli(capsys, "-f", str(deck_file))

    assert code == 0
    assert "Quiz stopped early." in out
    assert re.search(r"Total Questions \| 2\b", out)
    assert "Traceback" not in out + err
    assert "KeyboardInterrupt" not in out + err


def test_keyboard_interrupt_outside_a_question_exits_quietly(
    deck_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl+C while the deck is loading exits with code 130 and no traceback."""

    def interrupt(path: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "load_flashcards", interrupt)

    code, out, err = run_cli(capsys, "-f", str(deck_file))

    assert code == 130
    assert "Interrupted." in err
    assert "Traceback" not in out + err


def test_card_whose_answer_is_exit_is_scored_end_to_end(
    tmp_path: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression: a card with answer 'exit' accepts it instead of quitting."""
    deck = write_deck(
        tmp_path / "d.json",
        [
            {"front": "Command that leaves the shell?", "back": "exit"},
            {"front": "Capital of France?", "back": "Paris"},
        ],
    )
    feed_input(["EXIT", "Paris"])

    code, out, _ = run_cli(capsys, "-f", str(deck))

    assert code == 0
    assert "Quiz stopped early." not in out
    assert re.search(r"Total Questions \| 2\b", out)
    assert "perfect" in out


def test_exit_still_quits_on_card_with_different_answer(
    tmp_path: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """The bug fix is narrow: 'exit' on an ordinary card still quits."""
    deck = write_deck(
        tmp_path / "d.json",
        [
            {"front": "Command that leaves the shell?", "back": "exit"},
            {"front": "Capital of France?", "back": "Paris"},
        ],
    )
    feed_input(["exit", "exit"])  # scored, then quits on the second card

    code, out, _ = run_cli(capsys, "-f", str(deck))

    assert code == 0
    assert "Quiz stopped early." in out
    assert re.search(r"Total Questions \| 1\b", out)


def test_wrong_answer_reveals_expected_answer(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wrong answer prints the expected one."""
    feed_input(["nope", "Rome", "Madrid"])

    _, out, _ = run_cli(capsys, "-f", str(deck_file))

    assert "Incorrect. Expected: Paris" in out


def test_output_has_no_ansi_codes_when_not_a_tty(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """Captured (non-TTY) output is free of colour escapes."""
    feed_input(["Paris", "x", "Madrid"])

    _, out, _ = run_cli(capsys, "-f", str(deck_file))

    assert "\033" not in out


def test_mode_name_is_case_insensitive(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """--mode RANDOM is accepted."""
    feed_input([])

    code, out, _ = run_cli(capsys, "-f", str(deck_file), "--mode", "RANDOM")

    assert code == 0
    assert "Mode: random" in out


def test_main_reads_sys_argv_when_no_argv_given(
    deck_file: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() falls back to sys.argv[1:]."""
    monkeypatch.setattr(sys, "argv", ["main.py", "-f", str(deck_file)])
    feed_input([])

    assert main() == 0
    assert "Flashcard Quizzer" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Error paths
# --------------------------------------------------------------------------


def _assert_clean_error(code: int, out: str, err: str, needle: str) -> None:
    assert code == 1
    assert err.startswith("Error:")
    assert needle in err
    assert "Traceback" not in out + err
    assert "Flashcard Quizzer" not in out  # the quiz never started


def test_missing_file_gives_error_exit_code_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deck path that does not exist is a clean error."""
    code, out, err = run_cli(capsys, "-f", str(tmp_path / "nope.json"))

    _assert_clean_error(code, out, err, "File not found")


def test_malformed_json_gives_error_exit_code_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Broken JSON is a clean error with position."""
    path = tmp_path / "bad.json"
    path.write_text("[{", encoding="utf-8")

    code, out, err = run_cli(capsys, "-f", str(path))

    _assert_clean_error(code, out, err, "Invalid JSON")


def test_card_missing_back_gives_error_exit_code_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A card without 'back' is a clean error naming the field."""
    deck = write_deck(tmp_path / "d.json", [{"front": "only front"}])

    code, out, err = run_cli(capsys, "-f", str(deck))

    _assert_clean_error(code, out, err, "'back'")


def test_directory_as_deck_gives_error_exit_code_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A directory passed as deck is refused."""
    code, out, err = run_cli(capsys, "-f", str(tmp_path))

    _assert_clean_error(code, out, err, "is a directory")


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------


def test_stats_flag_shows_per_card_table(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """--stats adds the per-card breakdown; without it the table is absent."""
    feed_input(["Paris", "wrong", "Madrid"])
    _, with_stats, _ = run_cli(capsys, "-f", str(deck_file), "--stats")
    feed_input(["Paris", "wrong", "Madrid"])
    _, without_stats, _ = run_cli(capsys, "-f", str(deck_file))

    assert "Per-card breakdown:" in with_stats
    assert "| Card" in with_stats and "| Attempts | Correct |" in with_stats
    assert re.search(r"\| Capital of Italy\?\s+\| 1\s+\| 0\s+\|", with_stats)
    assert "Per-card breakdown" not in without_stats
    assert "=== Session Summary ===" in without_stats


def test_limit_flag_restricts_question_count(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """--limit 2 asks two questions and reports two cards in the greeting."""
    feed_input(["Paris", "Rome", "Madrid"])

    code, out, _ = run_cli(capsys, "-f", str(deck_file), "--limit", "2")

    assert code == 0
    assert len(asked_fronts(out)) == 2
    assert "Cards: 2" in out
    assert re.search(r"Total Questions \| 2\b", out)


def test_limit_larger_than_deck_is_capped_in_greeting(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """--limit 50 on a 3-card deck says 3 cards and asks 3."""
    feed_input(["Paris", "Rome", "Madrid"])

    _, out, _ = run_cli(capsys, "-f", str(deck_file), "--limit", "50")

    assert "Cards: 3" in out
    assert len(asked_fronts(out)) == 3


def _big_deck(tmp_path: Path) -> Path:
    return write_deck(
        tmp_path / "big.json",
        [{"front": f"Question {i}", "back": f"Answer {i}"} for i in range(12)],
    )


def test_seed_makes_random_mode_reproducible(
    tmp_path: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same --seed yields the same random order; the order is a permutation."""
    deck = _big_deck(tmp_path)
    orders: list[list[str]] = []
    for seed in ("11", "11", "12", "13"):
        feed_input(["x"] * 12)
        _, out, _ = run_cli(capsys, "-f", str(deck), "-m", "random", "--seed", seed)
        orders.append(asked_fronts(out))

    assert orders[0] == orders[1]
    assert sorted(orders[0]) == sorted(f"Question {i}" for i in range(12))
    assert orders[0] != [f"Question {i}" for i in range(12)] or orders[2] != orders[0]
    assert len({tuple(order) for order in orders}) > 1


def test_random_mode_without_seed_still_asks_whole_deck(
    tmp_path: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without a seed the order is arbitrary but complete."""
    deck = _big_deck(tmp_path)
    feed_input(["x"] * 12)

    _, out, _ = run_cli(capsys, "-f", str(deck), "-m", "random")

    assert sorted(asked_fronts(out)) == sorted(f"Question {i}" for i in range(12))


def test_adaptive_mode_repeats_missed_card(
    deck_file: Path, feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """In adaptive mode a wrong card is asked again until answered correctly."""
    feed_input(["wrong", "Rome", "Madrid", "Paris"])

    code, out, _ = run_cli(capsys, "-f", str(deck_file), "-m", "adaptive")

    assert code == 0
    fronts = asked_fronts(out)
    assert fronts == [
        "Capital of France?",
        "Capital of Italy?",
        "Capital of Spain?",
        "Capital of France?",
    ]
    assert re.search(r"Total Questions \| 4\b", out)
    assert re.search(r"Correct\s+\| 3\b", out)


# --------------------------------------------------------------------------
# History file
# --------------------------------------------------------------------------


def test_history_file_is_created_and_updated(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A run records misses; a later clean run decays them."""
    history = tmp_path / "history.json"
    feed_input(["Paris", "wrong", "Madrid"])
    code, _, _ = run_cli(capsys, "-f", str(deck_file), "--history-file", str(history))

    assert code == 0
    saved = json.loads(history.read_text(encoding="utf-8"))
    assert saved == {"version": 1, "miss_counts": {"Capital of Italy?": 1}}

    feed_input(["Paris", "wrong", "wrong"])
    run_cli(capsys, "-f", str(deck_file), "--history-file", str(history))
    saved = json.loads(history.read_text(encoding="utf-8"))
    assert saved["miss_counts"] == {"Capital of Italy?": 2, "Capital of Spain?": 1}

    feed_input(["Paris", "Rome", "Madrid"])
    run_cli(capsys, "-f", str(deck_file), "--history-file", str(history))
    saved = json.loads(history.read_text(encoding="utf-8"))
    assert saved["miss_counts"] == {"Capital of Italy?": 1}


def test_later_adaptive_run_asks_missed_card_first(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """History from one run makes the next adaptive run start with the weak card."""
    history = tmp_path / "history.json"
    feed_input(["Paris", "wrong", "Madrid"])
    run_cli(capsys, "-f", str(deck_file), "--history-file", str(history))

    feed_input(["Rome", "Paris", "Madrid"])
    code, out, _ = run_cli(
        capsys, "-f", str(deck_file), "-m", "adaptive", "--history-file", str(history)
    )

    assert code == 0
    assert asked_fronts(out)[0] == "Capital of Italy?"


def test_history_not_written_when_no_question_was_answered(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Quitting at the first prompt leaves no history file behind."""
    history = tmp_path / "history.json"
    feed_input(["exit"])

    code, _, _ = run_cli(capsys, "-f", str(deck_file), "--history-file", str(history))

    assert code == 0
    assert not history.exists()


def test_corrupt_history_file_warns_and_is_left_untouched(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A broken history file only triggers a warning; the quiz still runs."""
    history = tmp_path / "history.json"
    history.write_text("{definitely not json", encoding="utf-8")
    feed_input(["Paris", "Rome", "Madrid"])

    code, out, err = run_cli(
        capsys, "-f", str(deck_file), "--history-file", str(history)
    )

    assert code == 0
    assert "Warning: ignoring history file" in err
    assert "It will not be updated" in err
    assert "Traceback" not in out + err
    assert re.search(r"Total Questions \| 3\b", out)
    assert history.read_text(encoding="utf-8") == "{definitely not json"


def test_unwritable_history_location_warns_but_succeeds(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If the history cannot be saved (missing folder) the run still exits 0."""
    history = tmp_path / "missing_dir" / "history.json"
    feed_input(["Paris", "Rome", "Madrid"])

    code, out, err = run_cli(
        capsys, "-f", str(deck_file), "--history-file", str(history)
    )

    assert code == 0
    assert "Warning: could not update history file" in err
    assert "=== Session Summary ===" in out


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


def test_export_json_end_to_end(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--export results.json writes summary, per-card data and answers."""
    target = tmp_path / "results.json"
    feed_input(["Paris", "Milan", "Madrid"])

    code, _, err = run_cli(capsys, "-f", str(deck_file), "--export", str(target))

    assert code == 0
    assert err == ""
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["summary"]["total_questions"] == 3
    assert data["summary"]["correct"] == 2
    assert data["summary"]["accuracy_percent"] == 66.7
    assert data["summary"]["missed_terms"] == ["Capital of Italy?"]
    assert [a["user_answer"] for a in data["answers"]] == ["Paris", "Milan", "Madrid"]


def test_export_csv_end_to_end(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--export results.csv writes one row per answer."""
    target = tmp_path / "results.csv"
    feed_input(["Paris", "Milan", "Madrid"])

    code, _, _ = run_cli(capsys, "-f", str(deck_file), "--export", str(target))

    assert code == 0
    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["question", "front", "user_answer", "correct"]
    assert [row[3] for row in rows[1:]] == ["yes", "no", "yes"]
    assert len(rows) == 4


def test_export_csv_guards_formula_injection_end_to_end(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An answer like '=cmd' is stored with a leading apostrophe."""
    target = tmp_path / "results.csv"
    feed_input(["=cmd|' /C calc'!A0", "Rome", "Madrid"])

    code, _, _ = run_cli(capsys, "-f", str(deck_file), "--export", str(target))

    assert code == 0
    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[1][2] == "'=cmd|' /C calc'!A0"


def test_export_with_early_exit_still_writes_partial_results(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Quitting early exports the answers given so far."""
    target = tmp_path / "results.json"
    feed_input(["Paris", "exit"])

    code, _, _ = run_cli(capsys, "-f", str(deck_file), "--export", str(target))

    assert code == 0
    assert (
        json.loads(target.read_text(encoding="utf-8"))["summary"]["total_questions"]
        == 1
    )


def test_unsupported_export_extension_fails_before_any_question(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bad export extension is refused up front: nothing is asked or read."""
    stdin = feed_input(["Paris", "Rome", "Madrid"])
    target = tmp_path / "results.txt"

    code, out, err = run_cli(capsys, "-f", str(deck_file), "--export", str(target))

    assert code == 1
    assert err.startswith("Error:") and "Unsupported export format" in err
    assert "Q1:" not in out
    assert stdin.reads == 0
    assert not target.exists()


def test_export_to_directory_is_refused_before_the_quiz(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A directory cannot be an export target."""
    folder = tmp_path / "out.csv"
    folder.mkdir()
    stdin = feed_input(["Paris"])

    code, out, err = run_cli(capsys, "-f", str(deck_file), "--export", str(folder))

    assert code == 1
    assert "is a directory" in err
    assert "Q1:" not in out
    assert stdin.reads == 0


def test_export_to_missing_directory_is_refused_before_the_quiz(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The export folder must exist."""
    stdin = feed_input([])

    code, _, err = run_cli(
        capsys, "-f", str(deck_file), "--export", str(tmp_path / "no" / "r.json")
    )

    assert code == 1
    assert "does not exist" in err
    assert stdin.reads == 0


def test_export_failure_after_quiz_returns_one(
    deck_file: Path,
    tmp_path: Path,
    feed_input: FeedInput,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If writing the export fails after the quiz, report it and exit 1."""

    def boom(*args: Any, **kwargs: Any) -> None:
        raise ExportError("disk exploded")

    monkeypatch.setattr(main_module, "export_results", boom)
    feed_input(["Paris", "Rome", "Madrid"])

    code, out, err = run_cli(
        capsys, "-f", str(deck_file), "--export", str(tmp_path / "r.json")
    )

    assert code == 1
    assert "Error: disk exploded" in err
    assert "=== Session Summary ===" in out


# --------------------------------------------------------------------------
# Command line parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--mode", "random"],
        ["-f", "x.json", "--mode", "bogus"],
        ["-f", "x.json", "--limit", "0"],
        ["-f", "x.json", "--limit", "-2"],
        ["-f", "x.json", "--limit", "many"],
        ["-f", "x.json", "--seed", "abc"],
        ["-f", "x.json", "--unknown-flag"],
        ["-f"],
    ],
)
def test_invalid_arguments_exit_with_code_two(
    args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """argparse rejects bad invocations with exit status 2 and a usage line."""
    with pytest.raises(SystemExit) as info:
        main(args)

    assert info.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_help_exits_zero_and_mentions_every_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--help prints usage covering every option and exits 0."""
    with pytest.raises(SystemExit) as info:
        main(["--help"])

    assert info.value.code == 0
    out = capsys.readouterr().out
    for flag in (
        "-f",
        "--file",
        "-m",
        "--mode",
        "--stats",
        "--limit",
        "--seed",
        "--history-file",
        "--export",
        "-h",
        "--help",
    ):
        assert flag in out
    for mode_name in ("sequential", "random", "adaptive"):
        assert mode_name in out


def test_python_main_py_help_works_as_a_script() -> None:
    """`python main.py --help` runs in a fresh interpreter and returns 0."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )

    assert result.returncode == 0
    assert "--file" in result.stdout
    assert "Traceback" not in result.stderr


def test_parser_defaults() -> None:
    """Defaults: sequential mode, no stats, no limit/seed/history/export."""
    args = build_parser().parse_args(["-f", "deck.json"])

    assert args.mode == "sequential"
    assert args.stats is False
    assert args.limit is None
    assert args.seed is None
    assert args.history_file is None
    assert args.export is None
    assert args.file == Path("deck.json")


@pytest.mark.parametrize(
    "text, ok", [("1", True), ("25", True), ("0", False), ("-1", False), ("x", False)]
)
def test_positive_int_validator(text: str, ok: bool) -> None:
    """_positive_int accepts only integers >= 1."""
    if ok:
        assert main_module._positive_int(text) == int(text)
    else:
        with pytest.raises(argparse.ArgumentTypeError):
            main_module._positive_int(text)


# --------------------------------------------------------------------------
# Misc robustness
# --------------------------------------------------------------------------


def test_configure_streams_ignores_failing_reconfigure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stream whose reconfigure() fails, or that lacks it, is tolerated."""

    class Failing:
        def reconfigure(self, **kwargs: Any) -> None:
            raise ValueError("closed")

    class Recording:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        def reconfigure(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    recording = Recording()
    monkeypatch.setattr(sys, "stdin", Failing())
    monkeypatch.setattr(sys, "stdout", recording)
    monkeypatch.setattr(sys, "stderr", object())

    main_module._configure_streams()

    assert recording.kwargs == {"errors": "replace"}


def test_shipped_deck_runs_end_to_end(
    feed_input: FeedInput, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bundled deck can be quizzed with --limit and exits cleanly."""
    feed_input(["wrong", "wrong"])

    code, out, err = run_cli(
        capsys, "-f", str(PROJECT_ROOT / "data" / "git_commands.json"), "--limit", "2"
    )

    assert code == 0
    assert err == ""
    assert re.search(r"Total Questions \| 2\b", out)


def test_builtins_input_can_be_monkeypatched(
    deck_file: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() reads answers through builtins.input, so patching it works."""
    answers = iter(["Paris", "Milan", "Madrid"])
    prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)

    code, out, err = run_cli(capsys, "-f", str(deck_file))

    assert code == 0
    assert err == ""
    assert prompts == ["Your answer: "] * 3
    assert re.search(r"Correct\s+\| 2\b", out)
    assert "66.7" in out
