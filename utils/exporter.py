"""Export quiz session results to JSON or CSV."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Sequence

from quiz_engine import AnswerRecord, SessionStats
from utils.file_handler import FileHandlerError, write_json_atomic, write_text_atomic

SUPPORTED_EXTENSIONS = (".json", ".csv")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class ExportError(Exception):
    """Raised when the export target is invalid or cannot be written."""


def validate_export_path(path: str | Path) -> Path:
    """Check an export target before the quiz starts.

    Args:
        path: Requested export file path.

    Returns:
        The validated path.

    Raises:
        ExportError: If the extension is unsupported, the path is a directory
            or its parent directory does not exist.
    """
    target = Path(path)
    if target.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ExportError(
            f"Unsupported export format '{target.suffix or target.name}'. "
            f"Use one of: {', '.join(SUPPORTED_EXTENSIONS)}."
        )
    if target.is_dir():
        raise ExportError(f"Export path '{target}' is a directory, not a file.")
    if not target.resolve().parent.is_dir():
        raise ExportError(f"Export directory '{target.parent}' does not exist.")
    return target


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection in a text cell."""
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _to_csv(history: Sequence[AnswerRecord]) -> str:
    """Render the answer history as CSV text."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["question", "front", "user_answer", "correct"])
    for number, record in enumerate(history, start=1):
        writer.writerow(
            [
                number,
                _csv_safe(record.front),
                _csv_safe(record.user_answer),
                "yes" if record.correct else "no",
            ]
        )
    return buffer.getvalue()


def _to_json_data(stats: SessionStats, history: Sequence[AnswerRecord]) -> Any:
    """Build the JSON document for a session."""
    return {
        "summary": {
            "total_questions": stats.total_questions,
            "correct": stats.correct_count,
            "accuracy_percent": round(stats.accuracy_percent, 1),
            "missed_terms": list(stats.missed_terms),
        },
        "per_card": [
            {"front": front, "attempts": item.attempts, "correct": item.correct}
            for front, item in stats.per_card.items()
        ],
        "answers": [
            {
                "front": record.front,
                "user_answer": record.user_answer,
                "correct": record.correct,
            }
            for record in history
        ],
    }


def export_results(
    path: str | Path, stats: SessionStats, history: Sequence[AnswerRecord]
) -> None:
    """Write session results to ``path`` (format chosen by extension).

    Args:
        path: Destination file (``.json`` or ``.csv``).
        stats: Session statistics.
        history: Individual answers in the order they were given.

    Raises:
        ExportError: If the path is invalid or the file cannot be written.
    """
    target = validate_export_path(path)
    try:
        if target.suffix.lower() == ".json":
            write_json_atomic(target, _to_json_data(stats, history))
        else:
            write_text_atomic(target, _to_csv(history))
    except FileHandlerError as exc:
        raise ExportError(str(exc)) from exc
