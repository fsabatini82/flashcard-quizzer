"""Persist per-card miss counts across quiz sessions.

The history file is JSON: ``{"version": 1, "miss_counts": {"<front>": <int>}}``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from quiz_engine import SessionStats
from utils.file_handler import FileHandlerError, read_json_file, write_json_atomic

HISTORY_VERSION = 1


class HistoryError(Exception):
    """Raised when the history file cannot be used."""


def load_miss_counts(path: str | Path) -> dict[str, int]:
    """Load miss counts from a history file.

    A file that does not exist yet is not an error (first run).

    Args:
        path: Location of the history file.

    Returns:
        Miss counts keyed by card front.

    Raises:
        HistoryError: If the file exists but is unreadable or malformed.
    """
    history_path = Path(path)
    if not history_path.exists():
        return {}
    try:
        data: Any = read_json_file(history_path)
    except FileHandlerError as exc:
        raise HistoryError(str(exc)) from exc
    raw = data.get("miss_counts") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raise HistoryError(
            f"History file '{history_path}' has no 'miss_counts' object."
        )
    counts: dict[str, int] = {}
    for front, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise HistoryError(
                f"History file '{history_path}' has an invalid count for '{front}'."
            )
        counts[str(front)] = value
    return counts


def merge_session(counts: Mapping[str, int], stats: SessionStats) -> dict[str, int]:
    """Combine stored miss counts with one session's results.

    Each wrong answer adds one miss. A card answered correctly and never
    missed during the session loses one miss (never below zero), so mastered
    cards fade out of the priority list.

    Args:
        counts: Previously stored miss counts.
        stats: The finished session's statistics.

    Returns:
        The updated miss counts; cards with zero misses are dropped.
    """
    merged = dict(counts)
    for front, card in stats.per_card.items():
        misses = card.attempts - card.correct
        if misses:
            merged[front] = merged.get(front, 0) + misses
        elif front in merged:
            merged[front] = max(0, merged[front] - 1)
    return {front: count for front, count in merged.items() if count > 0}


def save_miss_counts(path: str | Path, counts: Mapping[str, int]) -> None:
    """Write miss counts to the history file atomically.

    Args:
        path: Location of the history file.
        counts: Miss counts keyed by card front.

    Raises:
        HistoryError: If the file cannot be written.
    """
    payload = {"version": HISTORY_VERSION, "miss_counts": dict(counts)}
    try:
        write_json_atomic(path, payload)
    except FileHandlerError as exc:
        raise HistoryError(str(exc)) from exc
