"""Tests for result export (utils/exporter.py)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from quiz_engine import AnswerRecord, CardStats, SessionStats
from utils.exporter import (
    ExportError,
    _csv_safe,
    export_results,
    validate_export_path,
)


@pytest.fixture
def history() -> list[AnswerRecord]:
    """Two answers: one right, one wrong."""
    return [
        AnswerRecord("Capital of France?", "paris", True),
        AnswerRecord("Capital of Italy?", "Milan", False),
    ]


@pytest.fixture
def stats() -> SessionStats:
    """Stats matching the ``history`` fixture."""
    return SessionStats(
        total_questions=2,
        correct_count=1,
        missed_terms=("Capital of Italy?",),
        per_card={
            "Capital of France?": CardStats(1, 1),
            "Capital of Italy?": CardStats(1, 0),
        },
    )


# -- validate_export_path ---------------------------------------------------


@pytest.mark.parametrize("name", ["r.json", "r.csv", "R.JSON", "r.CSV"])
def test_validate_accepts_supported_extensions(tmp_path: Path, name: str) -> None:
    """json and csv are accepted in any case; the path is returned."""
    target = tmp_path / name

    assert validate_export_path(target) == target


@pytest.mark.parametrize("name", ["r.txt", "r", "r.xml", ".json"])
def test_validate_rejects_unsupported_extension(tmp_path: Path, name: str) -> None:
    """Other extensions are refused with a list of supported ones."""
    with pytest.raises(ExportError, match=r"Unsupported export format.*\.json.*\.csv"):
        validate_export_path(tmp_path / name)


def test_validate_rejects_directory(tmp_path: Path) -> None:
    """A directory (even named like a file) is refused."""
    folder = tmp_path / "results.json"
    folder.mkdir()

    with pytest.raises(ExportError, match="is a directory"):
        validate_export_path(folder)


def test_validate_rejects_missing_parent(tmp_path: Path) -> None:
    """The parent directory must exist."""
    with pytest.raises(ExportError, match="does not exist"):
        validate_export_path(tmp_path / "missing" / "r.json")


def test_validate_accepts_relative_path_in_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare filename resolves against the current directory."""
    monkeypatch.chdir(tmp_path)

    assert validate_export_path("r.csv") == Path("r.csv")


# -- JSON -------------------------------------------------------------------


def test_export_json_content(
    tmp_path: Path, stats: SessionStats, history: list[AnswerRecord]
) -> None:
    """The JSON file has summary, per_card and answers sections."""
    target = tmp_path / "r.json"

    export_results(target, stats, history)

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["summary"] == {
        "total_questions": 2,
        "correct": 1,
        "accuracy_percent": 50.0,
        "missed_terms": ["Capital of Italy?"],
    }
    assert data["per_card"] == [
        {"front": "Capital of France?", "attempts": 1, "correct": 1},
        {"front": "Capital of Italy?", "attempts": 1, "correct": 0},
    ]
    assert data["answers"][1] == {
        "front": "Capital of Italy?",
        "user_answer": "Milan",
        "correct": False,
    }


def test_export_json_rounds_accuracy(tmp_path: Path) -> None:
    """Accuracy is rounded to one decimal place."""
    stats = SessionStats(total_questions=3, correct_count=2)
    target = tmp_path / "r.json"

    export_results(target, stats, [])

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["summary"]["accuracy_percent"] == 66.7


def test_export_uppercase_extension_uses_json_format(
    tmp_path: Path, stats: SessionStats, history: list[AnswerRecord]
) -> None:
    """Extension matching is case-insensitive when choosing the writer."""
    target = tmp_path / "R.JSON"

    export_results(target, stats, history)

    assert "summary" in json.loads(target.read_text(encoding="utf-8"))


def test_export_overwrites_existing_file(
    tmp_path: Path, stats: SessionStats, history: list[AnswerRecord]
) -> None:
    """An existing export is replaced."""
    target = tmp_path / "r.json"
    target.write_text("old", encoding="utf-8")

    export_results(target, stats, history)

    assert "summary" in json.loads(target.read_text(encoding="utf-8"))


# -- CSV --------------------------------------------------------------------


def test_export_csv_content(
    tmp_path: Path, stats: SessionStats, history: list[AnswerRecord]
) -> None:
    """The CSV has a header and one row per answer."""
    target = tmp_path / "r.csv"

    export_results(target, stats, history)

    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["question", "front", "user_answer", "correct"]
    assert rows[1] == ["1", "Capital of France?", "paris", "yes"]
    assert rows[2] == ["2", "Capital of Italy?", "Milan", "no"]


def test_export_csv_empty_history_has_only_header(
    tmp_path: Path, stats: SessionStats
) -> None:
    """No answers: just the header row."""
    target = tmp_path / "r.csv"

    export_results(target, stats, [])

    assert target.read_text(encoding="utf-8") == "question,front,user_answer,correct\n"


@pytest.mark.parametrize("payload", ["=cmd|' /C calc'!A0", "+1", "-2", "@SUM(A1)"])
def test_export_csv_neutralises_formula_injection(
    tmp_path: Path, stats: SessionStats, payload: str
) -> None:
    """Cells starting with = + - @ are prefixed with an apostrophe."""
    target = tmp_path / "r.csv"
    records = [AnswerRecord(payload, payload, False)]

    export_results(target, stats, records)

    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[1][1] == "'" + payload
    assert rows[1][2] == "'" + payload


@pytest.mark.parametrize("prefix", ["\t", "\r"])
def test_csv_safe_guards_tab_and_carriage_return(prefix: str) -> None:
    """Leading tab/CR (another injection vector) is also neutralised."""
    assert _csv_safe(prefix + "x") == "'" + prefix + "x"


def test_csv_safe_leaves_normal_text_alone() -> None:
    """Ordinary text and empty strings are unchanged."""
    assert _csv_safe("Paris") == "Paris"
    assert _csv_safe("") == ""
    assert _csv_safe("a=b") == "a=b"


def test_export_csv_quotes_commas_and_newlines(
    tmp_path: Path, stats: SessionStats
) -> None:
    """Commas, quotes and newlines survive a CSV round trip."""
    target = tmp_path / "r.csv"
    answer = 'a, "b"\nc'

    export_results(target, stats, [AnswerRecord("Q", answer, False)])

    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[1][2] == answer


# -- failures ---------------------------------------------------------------


def test_export_refuses_unsupported_extension(
    tmp_path: Path, stats: SessionStats, history: list[AnswerRecord]
) -> None:
    """export_results validates the path itself and writes nothing."""
    target = tmp_path / "r.txt"

    with pytest.raises(ExportError, match="Unsupported"):
        export_results(target, stats, history)

    assert not target.exists()


def test_export_wraps_write_failures(
    tmp_path: Path,
    stats: SessionStats,
    history: list[AnswerRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Low-level write errors surface as ExportError."""

    def broken_replace(src: object, dst: object) -> None:
        raise OSError(13, "Access is denied")

    monkeypatch.setattr("os.replace", broken_replace)

    with pytest.raises(ExportError, match="Access is denied"):
        export_results(tmp_path / "r.csv", stats, history)
    with pytest.raises(ExportError, match="Access is denied"):
        export_results(tmp_path / "r.json", stats, history)
