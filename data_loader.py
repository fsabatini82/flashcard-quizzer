"""Load and validate flashcard decks from JSON files.

Two layouts are accepted: a top-level array of cards, or an object with a
``"cards"`` array. Every card needs non-empty string ``front`` and ``back``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.file_handler import FileHandlerError, read_json_file

__all__ = ["Flashcard", "FlashcardLoadError", "load_flashcards", "parse_flashcards"]

_REQUIRED_FIELDS = ("front", "back")


@dataclass(frozen=True)
class Flashcard:
    """A single flashcard.

    Attributes:
        front: The prompt shown to the user.
        back: The expected answer.
    """

    front: str
    back: str


class FlashcardLoadError(Exception):
    """Raised when a deck cannot be loaded or fails validation."""


def _type_name(value: Any) -> str:
    """Return a JSON-style type name for an error message."""
    if value is None:
        return "null"
    return type(value).__name__


def _parse_card(position: int, raw: Any) -> Flashcard:
    """Validate one raw card.

    Args:
        position: 1-based card position used in error messages.
        raw: The decoded JSON value for the card.

    Returns:
        The validated, whitespace-stripped flashcard.

    Raises:
        FlashcardLoadError: If the card is malformed.
    """
    if not isinstance(raw, dict):
        raise FlashcardLoadError(
            f"Card #{position} must be an object with 'front' and 'back' "
            f"(found {_type_name(raw)})."
        )
    values: dict[str, str] = {}
    for field in _REQUIRED_FIELDS:
        if field not in raw:
            raise FlashcardLoadError(
                f"Card #{position} is missing required field '{field}'."
            )
        value = raw[field]
        if not isinstance(value, str):
            raise FlashcardLoadError(
                f"Card #{position} field '{field}' must be a string "
                f"(found {_type_name(value)})."
            )
        value = value.strip()
        if not value:
            raise FlashcardLoadError(f"Card #{position} field '{field}' is empty.")
        values[field] = value
    return Flashcard(front=values["front"], back=values["back"])


def parse_flashcards(data: Any) -> list[Flashcard]:
    """Validate decoded JSON and convert it into flashcards.

    Args:
        data: Decoded JSON, either a list of cards or ``{"cards": [...]}``.

    Returns:
        A non-empty list of flashcards with unique (case-insensitive) fronts.

    Raises:
        FlashcardLoadError: If the structure or any card is invalid.
    """
    raw_cards: Any = data
    if isinstance(data, dict):
        if "cards" not in data:
            raise FlashcardLoadError("Top-level object must contain a 'cards' array.")
        raw_cards = data["cards"]
    if not isinstance(raw_cards, list):
        raise FlashcardLoadError(
            "Deck must be an array of cards or an object with a 'cards' array "
            f"(found {_type_name(raw_cards)})."
        )
    if not raw_cards:
        raise FlashcardLoadError("The deck contains no cards.")

    cards: list[Flashcard] = []
    seen: dict[str, int] = {}
    for position, raw in enumerate(raw_cards, start=1):
        card = _parse_card(position, raw)
        key = card.front.casefold()
        if key in seen:
            raise FlashcardLoadError(
                f"Card #{position} has a duplicate front '{card.front}' "
                f"(same as card #{seen[key]})."
            )
        seen[key] = position
        cards.append(card)
    return cards


def load_flashcards(path: str | Path) -> list[Flashcard]:
    """Load a flashcard deck from a JSON file.

    Args:
        path: Location of the deck file.

    Returns:
        The validated flashcards in file order.

    Raises:
        FlashcardLoadError: If the file cannot be read or the deck is invalid.
    """
    try:
        data = read_json_file(Path(path))
    except FileHandlerError as exc:
        raise FlashcardLoadError(str(exc)) from exc
    return parse_flashcards(data)
