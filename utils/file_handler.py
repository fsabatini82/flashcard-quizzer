"""Safe file helpers: JSON reading and atomic writing with friendly errors.

All failures are converted to :class:`FileHandlerError` carrying a short,
user-facing message so callers never need to show a traceback.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class FileHandlerError(Exception):
    """Raised when a file cannot be read, parsed or written."""


def read_json_file(path: str | Path) -> Any:
    """Read and parse a UTF-8 JSON file.

    Args:
        path: Location of the JSON file.

    Returns:
        The decoded JSON value (list, dict, str, number, bool or None).

    Raises:
        FileHandlerError: If the file is missing, is a directory, cannot be
            read, is empty, is not valid UTF-8 or is not valid JSON.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileHandlerError(f"File not found: '{file_path}'.")
    if file_path.is_dir():
        raise FileHandlerError(f"'{file_path}' is a directory, not a file.")
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileHandlerError(
            f"'{file_path}' is not valid UTF-8 text ({exc.reason})."
        ) from exc
    except PermissionError as exc:
        raise FileHandlerError(f"Permission denied reading '{file_path}'.") from exc
    except OSError as exc:
        raise FileHandlerError(
            f"Could not read '{file_path}': {exc.strerror or exc}."
        ) from exc
    if not text.strip():
        raise FileHandlerError(f"File '{file_path}' is empty.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise FileHandlerError(
            f"Invalid JSON in '{file_path}' at line {exc.lineno}, "
            f"column {exc.colno}: {exc.msg}."
        ) from exc


def write_text_atomic(path: str | Path, text: str) -> None:
    """Write text to a file by writing a temp file and replacing the target.

    Args:
        path: Destination file path.
        text: Text content, written as UTF-8.

    Raises:
        FileHandlerError: If the path is a directory or the write fails.
    """
    target = Path(path)
    if target.is_dir():
        raise FileHandlerError(f"'{target}' is a directory, not a file.")
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, target)
        tmp_name = None
    except OSError as exc:
        raise FileHandlerError(
            f"Could not write '{target}': {exc.strerror or exc}."
        ) from exc
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def write_json_atomic(path: str | Path, data: Any) -> None:
    """Serialise data as pretty JSON and write it atomically.

    Args:
        path: Destination file path.
        data: JSON-serialisable value.

    Raises:
        FileHandlerError: If the data is not serialisable or the write fails.
    """
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    except (TypeError, ValueError) as exc:
        raise FileHandlerError(f"Data is not JSON serialisable: {exc}.") from exc
    write_text_atomic(path, text)
