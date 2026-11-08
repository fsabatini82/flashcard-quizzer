"""Tests for persisted miss counts (utils/history.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quiz_engine import CardStats, SessionStats
from utils.history import (
    HISTORY_VERSION,
    HistoryError,
    load_miss_counts,
    merge_session,
    save_miss_counts,
)


def _stats(per_card: dict[str, CardStats]) -> SessionStats:
    return SessionStats(
        total_questions=sum(c.attempts for c in per_card.values()),
        correct_count=sum(c.correct for c in per_card.values()),
        per_card=per_card,
    )


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


# -- load -------------------------------------------------------------------


def test_load_missing_file_means_no_history(tmp_path: Path) -> None:
    """A first run has no file, which is not an error."""
    assert load_miss_counts(tmp_path / "history.json") == {}


def test_load_valid_file(tmp_path: Path) -> None:
    """Valid history is returned as a dict of ints."""
    path = tmp_path / "h.json"
    _write(path, {"version": 1, "miss_counts": {"A": 2, "B": 0}})

    assert load_miss_counts(path) == {"A": 2, "B": 0}


def test_load_accepts_str_path(tmp_path: Path) -> None:
    """String paths are accepted."""
    path = tmp_path / "h.json"
    _write(path, {"miss_counts": {"A": 1}})

    assert load_miss_counts(str(path)) == {"A": 1}


@pytest.mark.parametrize("bad_count", [-1, 1.5, "3", None, True, [1]], ids=repr)
def test_load_rejects_invalid_counts(tmp_path: Path, bad_count: object) -> None:
    """Counts must be non-negative integers (booleans are not integers here)."""
    path = tmp_path / "h.json"
    _write(path, {"miss_counts": {"A": bad_count}})

    with pytest.raises(HistoryError, match="invalid count for 'A'"):
        load_miss_counts(path)


@pytest.mark.parametrize(
    "payload", [[], {"other": 1}, {"miss_counts": [1]}, {"miss_counts": None}, 5]
)
def test_load_rejects_wrong_structure(tmp_path: Path, payload: object) -> None:
    """Anything without a 'miss_counts' object is rejected."""
    path = tmp_path / "h.json"
    _write(path, payload)

    with pytest.raises(HistoryError, match="miss_counts"):
        load_miss_counts(path)


def test_load_wraps_malformed_json(tmp_path: Path) -> None:
    """Broken JSON surfaces as HistoryError (not FileHandlerError)."""
    path = tmp_path / "h.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(HistoryError, match="Invalid JSON"):
        load_miss_counts(path)


def test_load_wraps_empty_file(tmp_path: Path) -> None:
    """An empty history file is an error."""
    path = tmp_path / "h.json"
    path.write_text("", encoding="utf-8")

    with pytest.raises(HistoryError, match="is empty"):
        load_miss_counts(path)


def test_load_directory_is_an_error(tmp_path: Path) -> None:
    """A directory path exists but cannot be read as history."""
    with pytest.raises(HistoryError, match="is a directory"):
        load_miss_counts(tmp_path)


# -- merge ------------------------------------------------------------------


def test_merge_adds_one_miss_per_wrong_answer() -> None:
    """Every wrong attempt adds a miss."""
    stats = _stats({"A": CardStats(attempts=3, correct=1)})

    assert merge_session({"A": 1}, stats) == {"A": 3}


def test_merge_new_missed_card_starts_from_zero() -> None:
    """A card with no history gets its session misses."""
    stats = _stats({"A": CardStats(attempts=1, correct=0)})

    assert merge_session({}, stats) == {"A": 1}


def test_merge_decays_card_answered_correctly_without_misses() -> None:
    """A clean card loses one miss."""
    stats = _stats({"A": CardStats(attempts=1, correct=1)})

    assert merge_session({"A": 3}, stats) == {"A": 2}


def test_merge_drops_cards_that_reach_zero() -> None:
    """Counts that fall to zero are removed from the history."""
    stats = _stats({"A": CardStats(attempts=1, correct=1)})

    assert merge_session({"A": 1}, stats) == {}


def test_merge_never_goes_below_zero() -> None:
    """A stored zero stays out of the result and never becomes negative."""
    stats = _stats({"A": CardStats(attempts=1, correct=1)})

    assert merge_session({"A": 0}, stats) == {}


def test_merge_missed_then_correct_in_session_still_counts_the_miss() -> None:
    """A card that was wrong first and right later does not decay."""
    stats = _stats({"A": CardStats(attempts=2, correct=1)})

    assert merge_session({"A": 2}, stats) == {"A": 3}


def test_merge_keeps_untouched_cards() -> None:
    """Cards not asked this session keep their count."""
    stats = _stats({"B": CardStats(attempts=1, correct=1)})

    assert merge_session({"A": 4, "B": 1}, stats) == {"A": 4}


def test_merge_does_not_mutate_input() -> None:
    """The original mapping is left untouched."""
    original = {"A": 1}

    merge_session(original, _stats({"A": CardStats(1, 0)}))

    assert original == {"A": 1}


def test_merge_with_empty_session_changes_nothing() -> None:
    """No answers: counts are returned (minus zeros)."""
    assert merge_session({"A": 2, "Z": 0}, SessionStats()) == {"A": 2}


# -- save -------------------------------------------------------------------


def test_save_writes_versioned_payload(tmp_path: Path) -> None:
    """The file holds the version and the counts."""
    path = tmp_path / "h.json"

    save_miss_counts(path, {"A": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": HISTORY_VERSION,
        "miss_counts": {"A": 2},
    }


def test_save_then_load_round_trip(tmp_path: Path) -> None:
    """What is saved can be loaded back."""
    path = tmp_path / "h.json"

    save_miss_counts(path, {"Capital?": 4, "Caf\u00e9": 1})

    assert load_miss_counts(path) == {"Capital?": 4, "Caf\u00e9": 1}


def test_save_wraps_write_errors(tmp_path: Path) -> None:
    """Failure to write (here: a directory) becomes HistoryError."""
    with pytest.raises(HistoryError, match="is a directory"):
        save_miss_counts(tmp_path, {"A": 1})


def test_save_into_missing_directory_fails_cleanly(tmp_path: Path) -> None:
    """A missing parent directory is a HistoryError, not a crash."""
    with pytest.raises(HistoryError, match="Could not write"):
        save_miss_counts(tmp_path / "nope" / "h.json", {"A": 1})
