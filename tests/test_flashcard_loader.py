"""Tests for loading and validating flashcard decks (data_loader.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from data_loader import (
    Flashcard,
    FlashcardLoadError,
    load_flashcards,
    parse_flashcards,
)
from tests.helpers import write_deck

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def test_load_valid_flashcards_array(tmp_path: Path) -> None:
    """A top-level array of cards loads into Flashcard objects in order."""
    deck = write_deck(
        tmp_path / "deck.json",
        [
            {"front": "API", "back": "Application Programming Interface"},
            {"front": "CPU", "back": "Central Processing Unit"},
        ],
    )

    cards = load_flashcards(deck)

    assert cards == [
        Flashcard("API", "Application Programming Interface"),
        Flashcard("CPU", "Central Processing Unit"),
    ]


def test_load_invalid_json(tmp_path: Path) -> None:
    """Malformed JSON gives a friendly error with the location, no traceback."""
    path = tmp_path / "broken.json"
    path.write_text('[{"front": "a", "back": "b"', encoding="utf-8")

    with pytest.raises(FlashcardLoadError) as info:
        load_flashcards(path)

    message = str(info.value)
    assert "Invalid JSON" in message
    assert "line" in message and "column" in message
    assert "Traceback" not in message


def test_load_missing_required_field(tmp_path: Path) -> None:
    """A card without 'back' is rejected naming its position and the field."""
    deck = write_deck(
        tmp_path / "deck.json",
        [{"front": "ok", "back": "ok"}, {"front": "no answer here"}],
    )

    with pytest.raises(FlashcardLoadError) as info:
        load_flashcards(deck)

    message = str(info.value)
    assert "#2" in message
    assert "'back'" in message


def test_load_missing_front_field(tmp_path: Path) -> None:
    """A card without 'front' is rejected naming the field."""
    deck = write_deck(tmp_path / "deck.json", [{"back": "answer"}])

    with pytest.raises(FlashcardLoadError, match=r"#1.*'front'"):
        load_flashcards(deck)


def test_load_wrapper_object_with_cards_key(tmp_path: Path) -> None:
    """The {"cards": [...]} layout is accepted."""
    deck = write_deck(tmp_path / "deck.json", {"cards": [{"front": "Q", "back": "A"}]})

    assert load_flashcards(deck) == [Flashcard("Q", "A")]


@pytest.mark.parametrize(
    "name, expected_count",
    [
        ("glossary.json", 10),
        ("python_basics.json", None),
        ("git_commands.json", 13),
        ("server_acronyms.json", 14),
    ],
)
def test_bundled_decks_load(name: str, expected_count: int | None) -> None:
    """Every deck shipped in data/ loads and has non-empty unique cards."""
    cards = load_flashcards(DATA_DIR / name)

    assert cards
    if expected_count is not None:
        assert len(cards) == expected_count
    assert all(card.front and card.back for card in cards)
    fronts = [card.front.casefold() for card in cards]
    assert len(fronts) == len(set(fronts))


def test_load_accepts_str_path(deck_file: Path) -> None:
    """load_flashcards accepts a plain string path as well as a Path."""
    assert len(load_flashcards(str(deck_file))) == 3


def test_load_missing_file(tmp_path: Path) -> None:
    """A missing file raises a 'File not found' error."""
    with pytest.raises(FlashcardLoadError, match="File not found"):
        load_flashcards(tmp_path / "nope.json")


def test_load_directory_path(tmp_path: Path) -> None:
    """Passing a directory instead of a file is reported clearly."""
    with pytest.raises(FlashcardLoadError, match="is a directory"):
        load_flashcards(tmp_path)


def test_load_empty_file(tmp_path: Path) -> None:
    """An empty (or whitespace-only) file is reported as empty."""
    path = tmp_path / "empty.json"
    path.write_text("  \n", encoding="utf-8")

    with pytest.raises(FlashcardLoadError, match="is empty"):
        load_flashcards(path)


def test_load_non_utf8_file(tmp_path: Path) -> None:
    """Bytes that are not valid UTF-8 are reported without a traceback."""
    path = tmp_path / "latin.json"
    path.write_bytes(b'[{"front": "caf\xe9", "back": "x"}]')

    with pytest.raises(FlashcardLoadError, match="not valid UTF-8") as info:
        load_flashcards(path)

    assert "Traceback" not in str(info.value)


def test_load_file_with_utf8_bom(tmp_path: Path) -> None:
    """A UTF-8 BOM (common on Windows) is tolerated."""
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'[{"front": "Q", "back": "A"}]')

    assert load_flashcards(path) == [Flashcard("Q", "A")]


def test_load_unicode_content(tmp_path: Path) -> None:
    """Non-ASCII text round-trips through the loader."""
    deck = write_deck(
        tmp_path / "deck.json", [{"front": "Caf\u00e9?", "back": "\u2615"}]
    )

    assert load_flashcards(deck) == [Flashcard("Caf\u00e9?", "\u2615")]


@pytest.mark.parametrize("payload", ['"just a string"', "42", "null", "true"])
def test_load_top_level_wrong_type(tmp_path: Path, payload: str) -> None:
    """A top-level JSON scalar is not a deck."""
    path = tmp_path / "scalar.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(FlashcardLoadError, match="array of cards"):
        load_flashcards(path)


def test_load_object_without_cards_key(tmp_path: Path) -> None:
    """An object lacking a 'cards' key is rejected."""
    deck = write_deck(tmp_path / "deck.json", {"questions": []})

    with pytest.raises(FlashcardLoadError, match="'cards'"):
        load_flashcards(deck)


def test_load_cards_key_not_a_list(tmp_path: Path) -> None:
    """If 'cards' is not an array the error mentions the found type."""
    deck = write_deck(tmp_path / "deck.json", {"cards": "oops"})

    with pytest.raises(FlashcardLoadError, match="found str"):
        load_flashcards(deck)


@pytest.mark.parametrize("data", [[], {"cards": []}])
def test_load_empty_deck(tmp_path: Path, data: Any) -> None:
    """A deck with no cards is an error."""
    deck = write_deck(tmp_path / "deck.json", data)

    with pytest.raises(FlashcardLoadError, match="no cards"):
        load_flashcards(deck)


@pytest.mark.parametrize(
    "raw, type_name",
    [("text", "str"), (7, "int"), (None, "null"), ([1], "list")],
)
def test_load_non_object_card(tmp_path: Path, raw: Any, type_name: str) -> None:
    """A card that is not an object is rejected, naming its type."""
    deck = write_deck(tmp_path / "deck.json", [{"front": "a", "back": "b"}, raw])

    with pytest.raises(FlashcardLoadError) as info:
        load_flashcards(deck)

    assert "#2" in str(info.value)
    assert f"found {type_name}" in str(info.value)


@pytest.mark.parametrize("bad", [5, None, ["x"], True])
def test_load_non_string_field(tmp_path: Path, bad: Any) -> None:
    """Card fields must be strings."""
    deck = write_deck(tmp_path / "deck.json", [{"front": "q", "back": bad}])

    with pytest.raises(FlashcardLoadError, match="'back' must be a string"):
        load_flashcards(deck)


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_load_whitespace_only_field(tmp_path: Path, blank: str) -> None:
    """Empty or whitespace-only fields are rejected as empty."""
    deck = write_deck(tmp_path / "deck.json", [{"front": blank, "back": "b"}])

    with pytest.raises(FlashcardLoadError, match="'front' is empty"):
        load_flashcards(deck)


def test_load_strips_surrounding_whitespace(tmp_path: Path) -> None:
    """Leading/trailing whitespace is removed from both fields."""
    deck = write_deck(tmp_path / "deck.json", [{"front": "  Q \n", "back": "\tA  "}])

    assert load_flashcards(deck) == [Flashcard("Q", "A")]


def test_load_duplicate_fronts_case_insensitive(tmp_path: Path) -> None:
    """Fronts that differ only by case or padding count as duplicates."""
    deck = write_deck(
        tmp_path / "deck.json",
        [
            {"front": "DNS", "back": "one"},
            {"front": "Other", "back": "two"},
            {"front": " dns ", "back": "three"},
        ],
    )

    with pytest.raises(FlashcardLoadError) as info:
        load_flashcards(deck)

    message = str(info.value)
    assert "duplicate" in message
    assert "#3" in message and "#1" in message


def test_same_back_for_different_fronts_is_allowed(tmp_path: Path) -> None:
    """Only fronts must be unique; answers may repeat."""
    deck = write_deck(
        tmp_path / "deck.json",
        [{"front": "a", "back": "same"}, {"front": "b", "back": "same"}],
    )

    assert len(load_flashcards(deck)) == 2


def test_parse_flashcards_does_not_need_a_file() -> None:
    """parse_flashcards validates already-decoded data."""
    assert parse_flashcards([{"front": "Q", "back": "A"}]) == [Flashcard("Q", "A")]


def test_flashcard_is_immutable() -> None:
    """Flashcard is a frozen dataclass."""
    card = Flashcard("Q", "A")

    with pytest.raises(AttributeError):
        card.front = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    "content",
    [
        "[",
        "",
        '{"cards": [{"front": "a"}]}',
        '[{"front": 1, "back": 2}]',
        "[]",
        '{"x": 1}',
    ],
)
def test_error_messages_never_contain_traceback(tmp_path: Path, content: str) -> None:
    """No failure mode leaks a traceback into the user-facing message."""
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(FlashcardLoadError) as info:
        load_flashcards(path)

    assert "Traceback" not in str(info.value)
    assert str(info.value)


def test_json_dump_round_trip(tmp_path: Path) -> None:
    """Cards written by json.dumps with unicode escapes load unchanged."""
    path = tmp_path / "deck.json"
    path.write_text(
        json.dumps([{"front": "\u00fc", "back": "\u00df"}], ensure_ascii=True),
        encoding="utf-8",
    )

    assert load_flashcards(path) == [Flashcard("\u00fc", "\u00df")]
