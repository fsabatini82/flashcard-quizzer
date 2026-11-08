"""Tests for the safe file helpers (utils/file_handler.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from utils.file_handler import (
    FileHandlerError,
    read_json_file,
    write_json_atomic,
    write_text_atomic,
)

# -- read_json_file ---------------------------------------------------------


def test_read_json_file_returns_decoded_value(tmp_path: Path) -> None:
    """Valid JSON is decoded."""
    path = tmp_path / "a.json"
    path.write_text('{"k": [1, 2]}', encoding="utf-8")

    assert read_json_file(path) == {"k": [1, 2]}


def test_read_json_file_accepts_str_path(tmp_path: Path) -> None:
    """Plain string paths work too."""
    path = tmp_path / "a.json"
    path.write_text("[1]", encoding="utf-8")

    assert read_json_file(str(path)) == [1]


def test_read_json_file_missing(tmp_path: Path) -> None:
    """A missing file gives a 'File not found' error."""
    with pytest.raises(FileHandlerError, match="File not found"):
        read_json_file(tmp_path / "missing.json")


def test_read_json_file_directory(tmp_path: Path) -> None:
    """A directory is not a file."""
    with pytest.raises(FileHandlerError, match="is a directory"):
        read_json_file(tmp_path)


def test_read_json_file_empty(tmp_path: Path) -> None:
    """An empty file is reported as empty, not as bad JSON."""
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")

    with pytest.raises(FileHandlerError, match="is empty"):
        read_json_file(path)


def test_read_json_file_invalid_json_reports_position(tmp_path: Path) -> None:
    """Syntax errors include line and column."""
    path = tmp_path / "bad.json"
    path.write_text('{\n  "a": 1,\n  oops\n}', encoding="utf-8")

    with pytest.raises(FileHandlerError, match=r"line 3, column 3"):
        read_json_file(path)


def test_read_json_file_non_utf8(tmp_path: Path) -> None:
    """Invalid UTF-8 bytes are reported."""
    path = tmp_path / "bin.json"
    path.write_bytes(b"\xff\xfe\x00\x80")

    with pytest.raises(FileHandlerError, match="not valid UTF-8"):
        read_json_file(path)


def test_read_json_file_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PermissionError becomes a friendly message."""
    path = tmp_path / "locked.json"
    path.write_text("[]", encoding="utf-8")

    def deny(self: Path, *args: Any, **kwargs: Any) -> str:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", deny)

    with pytest.raises(FileHandlerError, match="Permission denied"):
        read_json_file(path)


def test_read_json_file_generic_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Other OSErrors are wrapped with the system message."""
    path = tmp_path / "io.json"
    path.write_text("[]", encoding="utf-8")

    def fail(self: Path, *args: Any, **kwargs: Any) -> str:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(Path, "read_text", fail)

    with pytest.raises(FileHandlerError, match="Input/output error"):
        read_json_file(path)


# -- write_text_atomic ------------------------------------------------------


def test_write_text_atomic_creates_and_overwrites(tmp_path: Path) -> None:
    """The file is created, then replaced on the next write."""
    path = tmp_path / "out.txt"

    write_text_atomic(path, "one")
    assert path.read_text(encoding="utf-8") == "one"
    write_text_atomic(path, "two")
    assert path.read_text(encoding="utf-8") == "two"


def test_write_text_atomic_leaves_no_temp_files(tmp_path: Path) -> None:
    """Only the target remains in the directory after a successful write."""
    write_text_atomic(tmp_path / "out.txt", "x")

    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]


def test_write_text_atomic_preserves_newlines(tmp_path: Path) -> None:
    """Text is written verbatim (no newline translation)."""
    path = tmp_path / "out.txt"

    write_text_atomic(path, "a\nb\n")

    assert path.read_bytes() == b"a\nb\n"


def test_write_text_atomic_writes_utf8(tmp_path: Path) -> None:
    """Non-ASCII text is stored as UTF-8."""
    path = tmp_path / "out.txt"

    write_text_atomic(path, "caf\u00e9")

    assert path.read_bytes() == "caf\u00e9".encode("utf-8")


def test_write_text_atomic_rejects_directory(tmp_path: Path) -> None:
    """Writing onto a directory is refused."""
    with pytest.raises(FileHandlerError, match="is a directory"):
        write_text_atomic(tmp_path, "x")


def test_write_text_atomic_missing_parent_directory(tmp_path: Path) -> None:
    """A missing parent directory yields a 'Could not write' error."""
    with pytest.raises(FileHandlerError, match="Could not write"):
        write_text_atomic(tmp_path / "no" / "such" / "out.txt", "x")


def test_write_text_atomic_cleans_temp_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the final replace fails the temp file is removed and the target kept."""
    target = tmp_path / "out.txt"
    target.write_text("original", encoding="utf-8")

    def broken_replace(src: Any, dst: Any) -> None:
        raise OSError(13, "Access is denied")

    monkeypatch.setattr("os.replace", broken_replace)

    with pytest.raises(FileHandlerError, match="Access is denied"):
        write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]


def test_write_text_atomic_tolerates_failed_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing cleanup does not mask the original write error."""

    def broken_replace(src: Any, dst: Any) -> None:
        raise OSError(13, "Access is denied")

    def broken_unlink(path: Any) -> None:
        raise OSError(32, "In use")

    monkeypatch.setattr("os.replace", broken_replace)
    monkeypatch.setattr("os.unlink", broken_unlink)

    with pytest.raises(FileHandlerError, match="Access is denied"):
        write_text_atomic(tmp_path / "out.txt", "new")


# -- write_json_atomic ------------------------------------------------------


def test_write_json_atomic_round_trip(tmp_path: Path) -> None:
    """Data written can be read back; output is indented and newline-ended."""
    path = tmp_path / "d.json"
    data = {"name": "caf\u00e9", "n": [1, 2]}

    write_json_atomic(path, data)

    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert "\n  " in text  # indented
    assert "caf\u00e9" in text  # ensure_ascii=False
    assert json.loads(text) == data
    assert read_json_file(path) == data


def test_write_json_atomic_rejects_unserialisable_data(tmp_path: Path) -> None:
    """Non-JSON values raise FileHandlerError and write nothing."""
    path = tmp_path / "d.json"

    with pytest.raises(FileHandlerError, match="not JSON serialisable"):
        write_json_atomic(path, {"bad": object()})

    assert not path.exists()


def test_write_json_atomic_rejects_circular_data(tmp_path: Path) -> None:
    """ValueError from circular references is also converted."""
    circular: list[Any] = []
    circular.append(circular)

    with pytest.raises(FileHandlerError, match="not JSON serialisable"):
        write_json_atomic(tmp_path / "d.json", circular)
