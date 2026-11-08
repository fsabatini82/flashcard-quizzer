"""Entry point for the Flashcard Quizzer CLI.

This module only wires together argument parsing, deck loading, the quiz
engine and the terminal UI. Run ``python main.py --help`` for usage.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Sequence

from data_loader import Flashcard, FlashcardLoadError, load_flashcards
from quiz_engine import AVAILABLE_MODES, QuizSession, create_mode
from ui import QuizExit, QuizUI
from utils.exporter import ExportError, export_results, validate_export_path
from utils.history import (
    HistoryError,
    load_miss_counts,
    merge_session,
    save_miss_counts,
)


def _positive_int(text: str) -> int:
    """Parse a strictly positive integer for argparse.

    Args:
        text: Raw command-line value.

    Returns:
        The parsed integer.

    Raises:
        argparse.ArgumentTypeError: If the value is not a positive integer.
    """
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not an integer") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Flashcard Quizzer: test yourself with flashcards from a "
        "JSON deck. Type 'exit' or 'quit' at any prompt to stop early.",
    )
    parser.add_argument(
        "-f",
        "--file",
        type=Path,
        required=True,
        help="path to the JSON flashcard deck",
    )
    parser.add_argument(
        "-m",
        "--mode",
        type=str.lower,
        choices=AVAILABLE_MODES,
        default="sequential",
        help="question order: sequential (deck order), random, or adaptive "
        "(weak cards first, missed cards repeat) (default: %(default)s)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="add a detailed per-card table (attempts and correct answers) "
        "to the summary; the basic summary is always shown",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        metavar="N",
        help="only ask the first N cards after the mode's ordering",
    )
    parser.add_argument(
        "--seed",
        type=int,
        metavar="INT",
        help="random seed for reproducible order; only affects random mode "
        "(ignored in other modes)",
    )
    parser.add_argument(
        "--history-file",
        type=Path,
        metavar="PATH",
        help="JSON file that stores per-card miss counts across sessions; "
        "adaptive mode asks previously missed cards first",
    )
    parser.add_argument(
        "--export",
        type=Path,
        metavar="PATH",
        help="write the session results to PATH (.json or .csv)",
    )
    return parser


def run_quiz(session: QuizSession, ui: QuizUI) -> None:
    """Ask questions until the deck is finished or the user quits.

    Args:
        session: The session supplying cards and scoring answers.
        ui: The terminal UI.
    """
    index = 0
    try:
        while True:
            card: Flashcard | None = session.next_card()
            if card is None:
                return
            index += 1
            answer = ui.ask(card, index)
            correct = session.submit(card, answer)
            ui.show_feedback(correct, card.back)
    except (QuizExit, KeyboardInterrupt):
        ui.show_goodbye()


def _configure_streams() -> None:
    """Make console streams tolerant of characters the codec cannot handle."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def _load_history(path: Path | None, ui: QuizUI) -> tuple[dict[str, int], bool]:
    """Load stored miss counts, warning instead of failing.

    Args:
        path: History file path, or ``None`` when persistence is off.
        ui: UI used to display warnings.

    Returns:
        The miss counts and whether the history file may be updated later.
    """
    if path is None:
        return {}, False
    try:
        return load_miss_counts(path), True
    except HistoryError as exc:
        ui.show_warning(f"ignoring history file: {exc} It will not be updated.")
        return {}, False


def main(argv: Sequence[str] | None = None) -> int:
    """Run the quizzer.

    Ctrl+C during a question ends the quiz and still shows the summary.
    Ctrl+C at any other moment (loading, summary, saving) exits quietly.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: 0 on success, 1 on load or validation errors,
        130 when interrupted outside a question. Invalid flags make argparse
        exit with code 2.
    """
    args = build_parser().parse_args(argv)
    _configure_streams()
    try:
        return _run(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


def _run(args: argparse.Namespace) -> int:
    """Load the deck, run the quiz and save or export the results.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Process exit code: 0 on success, 1 on load, validation or export errors.
    """
    try:
        if args.export is not None:
            validate_export_path(args.export)
        cards = load_flashcards(args.file)
    except (ExportError, FlashcardLoadError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    ui = QuizUI()
    miss_counts, can_save = _load_history(args.history_file, ui)
    rng = random.Random(args.seed) if args.seed is not None else None
    mode = create_mode(
        args.mode, cards, rng=rng, miss_counts=miss_counts, limit=args.limit
    )
    session = QuizSession(mode)

    ui.show_welcome(
        len(cards) if args.limit is None else min(args.limit, len(cards)), mode.name
    )
    run_quiz(session, ui)
    stats = session.stats()
    ui.show_summary(stats, detailed=args.stats)

    exit_code = 0
    if can_save and stats.total_questions:
        try:
            save_miss_counts(args.history_file, merge_session(miss_counts, stats))
        except HistoryError as exc:
            ui.show_warning(f"could not update history file: {exc}")
    if args.export is not None:
        try:
            export_results(args.export, stats, session.history)
        except ExportError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
