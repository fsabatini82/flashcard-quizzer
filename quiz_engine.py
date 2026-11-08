"""Quiz logic: question-ordering strategies, a mode factory and scoring.

This module is UI-free. Question ordering follows the Strategy pattern
(:class:`QuizMode` and its subclasses) and modes are built through
:func:`create_mode`, a small registry-based Factory. To add a new mode,
write a :class:`QuizMode` subclass and add it to ``_MODE_REGISTRY``.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from itertools import islice
from typing import Deque, Mapping, Sequence

from data_loader import Flashcard

REINSERT_GAP = 3
"""Number of other cards shown before a missed card returns in adaptive mode."""


def normalize_answer(text: str) -> str:
    """Normalise an answer for comparison.

    Args:
        text: Raw answer text.

    Returns:
        The text trimmed, with internal whitespace collapsed and case folded.
    """
    return " ".join(text.split()).casefold()


class QuizMode(ABC):
    """Strategy interface deciding which card is asked next."""

    def __init__(self, cards: Sequence[Flashcard]) -> None:
        """Store the deck.

        Args:
            cards: Cards available to the quiz.
        """
        self._cards: tuple[Flashcard, ...] = tuple(cards)

    @classmethod
    def create(
        cls,
        cards: Sequence[Flashcard],
        *,
        rng: random.Random | None = None,
        miss_counts: Mapping[str, int] | None = None,
    ) -> QuizMode:
        """Build an instance from the factory's common options.

        Subclasses override this to pick the options they care about.

        Args:
            cards: Cards available to the quiz.
            rng: Optional random generator (used by randomised modes).
            miss_counts: Optional historical miss counts keyed by card front.

        Returns:
            A new mode instance.
        """
        return cls(cards)

    @property
    @abstractmethod
    def name(self) -> str:
        """The registry name of this mode."""

    @abstractmethod
    def next_card(self) -> Flashcard | None:
        """Return the next card to ask.

        Returns:
            The next card, or ``None`` when the quiz is finished.
        """

    @abstractmethod
    def limit_to(self, count: int) -> None:
        """Keep only the first ``count`` cards of the mode's ordering.

        Args:
            count: Maximum number of cards to ask; must be positive.
        """

    def record_result(self, card: Flashcard, correct: bool) -> None:
        """Hook called after each answer. The default does nothing.

        Args:
            card: The card that was answered.
            correct: Whether the answer was correct.
        """


class _QueueMode(QuizMode):
    """Shared base for modes that serve cards from a queue."""

    def __init__(self, cards: Sequence[Flashcard]) -> None:
        """Order the deck once using :meth:`_initial_order`.

        Args:
            cards: Cards available to the quiz.
        """
        super().__init__(cards)
        self._queue: Deque[Flashcard] = deque(self._initial_order(self._cards))

    @abstractmethod
    def _initial_order(self, cards: Sequence[Flashcard]) -> list[Flashcard]:
        """Return the cards in the order they should first be asked."""

    def next_card(self) -> Flashcard | None:
        """Pop the next card from the queue.

        Returns:
            The next card, or ``None`` when the queue is empty.
        """
        if not self._queue:
            return None
        return self._queue.popleft()

    def limit_to(self, count: int) -> None:
        """Truncate the queue to its first ``count`` cards.

        Args:
            count: Maximum number of cards to keep; must be positive.

        Raises:
            ValueError: If ``count`` is not positive.
        """
        if count < 1:
            raise ValueError("limit must be a positive integer")
        self._queue = deque(islice(self._queue, count))


class SequentialMode(_QueueMode):
    """Ask every card once, in deck order."""

    @property
    def name(self) -> str:
        """The registry name of this mode."""
        return "sequential"

    def _initial_order(self, cards: Sequence[Flashcard]) -> list[Flashcard]:
        """Keep the deck order."""
        return list(cards)


class RandomMode(_QueueMode):
    """Ask every card once, in a random order fixed at start-up."""

    def __init__(
        self, cards: Sequence[Flashcard], rng: random.Random | None = None
    ) -> None:
        """Shuffle the deck once.

        Args:
            cards: Cards available to the quiz.
            rng: Optional generator, e.g. seeded for reproducible runs.
        """
        self._rng = rng if rng is not None else random.Random()
        super().__init__(cards)

    @classmethod
    def create(
        cls,
        cards: Sequence[Flashcard],
        *,
        rng: random.Random | None = None,
        miss_counts: Mapping[str, int] | None = None,
    ) -> QuizMode:
        """Build a random mode using the supplied generator.

        Args:
            cards: Cards available to the quiz.
            rng: Optional random generator.
            miss_counts: Ignored.

        Returns:
            A new :class:`RandomMode`.
        """
        return cls(cards, rng)

    @property
    def name(self) -> str:
        """The registry name of this mode."""
        return "random"

    def _initial_order(self, cards: Sequence[Flashcard]) -> list[Flashcard]:
        """Return a shuffled copy of the deck."""
        shuffled = list(cards)
        self._rng.shuffle(shuffled)
        return shuffled


class AdaptiveMode(_QueueMode):
    """Prioritise weak cards and repeat missed ones until answered correctly.

    The session starts with previously missed cards first (most misses first,
    deck order otherwise). A card answered incorrectly is re-queued
    :data:`REINSERT_GAP` positions ahead (or at the end if fewer cards remain)
    and keeps returning until it is answered correctly. A card answered
    correctly is never asked again.
    """

    def __init__(
        self,
        cards: Sequence[Flashcard],
        miss_counts: Mapping[str, int] | None = None,
    ) -> None:
        """Order the deck by historical misses.

        Args:
            cards: Cards available to the quiz.
            miss_counts: Optional historical miss counts keyed by card front
                (matched case-insensitively).
        """
        self._miss_counts = {
            front.casefold(): count for front, count in (miss_counts or {}).items()
        }
        super().__init__(cards)

    @classmethod
    def create(
        cls,
        cards: Sequence[Flashcard],
        *,
        rng: random.Random | None = None,
        miss_counts: Mapping[str, int] | None = None,
    ) -> QuizMode:
        """Build an adaptive mode seeded with historical miss counts.

        Args:
            cards: Cards available to the quiz.
            rng: Ignored.
            miss_counts: Optional historical miss counts keyed by card front.

        Returns:
            A new :class:`AdaptiveMode`.
        """
        return cls(cards, miss_counts)

    @property
    def name(self) -> str:
        """The registry name of this mode."""
        return "adaptive"

    def _initial_order(self, cards: Sequence[Flashcard]) -> list[Flashcard]:
        """Sort by miss count descending; the sort is stable."""
        return sorted(
            cards, key=lambda card: -self._miss_counts.get(card.front.casefold(), 0)
        )

    def record_result(self, card: Flashcard, correct: bool) -> None:
        """Re-queue a card that was answered incorrectly.

        Args:
            card: The card that was answered.
            correct: Whether the answer was correct.
        """
        if correct or card in self._queue:
            return
        self._queue.insert(min(REINSERT_GAP, len(self._queue)), card)


_MODE_REGISTRY: dict[str, type[QuizMode]] = {
    "sequential": SequentialMode,
    "random": RandomMode,
    "adaptive": AdaptiveMode,
}

AVAILABLE_MODES: tuple[str, ...] = tuple(sorted(_MODE_REGISTRY))
"""Valid mode names, suitable for argparse ``choices``."""


def create_mode(
    name: str,
    cards: Sequence[Flashcard],
    *,
    rng: random.Random | None = None,
    miss_counts: Mapping[str, int] | None = None,
    limit: int | None = None,
) -> QuizMode:
    """Create a quiz mode by name.

    Args:
        name: Mode name; case-insensitive and surrounding space is ignored.
        cards: Cards available to the quiz.
        rng: Optional random generator for randomised modes.
        miss_counts: Optional historical miss counts keyed by card front.
        limit: Optional maximum number of cards, applied after ordering.

    Returns:
        The configured quiz mode.

    Raises:
        ValueError: If the name is unknown or ``limit`` is not positive.
    """
    mode_class = _MODE_REGISTRY.get(name.strip().casefold())
    if mode_class is None:
        raise ValueError(
            f"Unknown mode '{name}'. Valid choices: {', '.join(AVAILABLE_MODES)}."
        )
    mode = mode_class.create(cards, rng=rng, miss_counts=miss_counts)
    if limit is not None:
        mode.limit_to(limit)
    return mode


@dataclass(frozen=True)
class AnswerRecord:
    """One submitted answer.

    Attributes:
        front: The card prompt that was asked.
        user_answer: The answer as typed by the user.
        correct: Whether the answer was judged correct.
    """

    front: str
    user_answer: str
    correct: bool


@dataclass
class CardStats:
    """Per-card counters.

    Attributes:
        attempts: How many times the card was answered.
        correct: How many of those answers were correct.
    """

    attempts: int = 0
    correct: int = 0


@dataclass(frozen=True)
class SessionStats:
    """Snapshot of a session's results.

    Attributes:
        total_questions: Number of answers submitted.
        correct_count: Number of correct answers.
        missed_terms: Fronts answered wrong at least once, in first-miss order.
        per_card: Attempts and correct counts per card front.
    """

    total_questions: int = 0
    correct_count: int = 0
    missed_terms: tuple[str, ...] = ()
    per_card: Mapping[str, CardStats] = field(default_factory=dict)

    @property
    def accuracy_percent(self) -> float:
        """Percentage of correct answers; ``0.0`` when nothing was asked."""
        if self.total_questions == 0:
            return 0.0
        return self.correct_count / self.total_questions * 100.0


class QuizSession:
    """Run-time state of one quiz: serves cards and scores answers."""

    def __init__(self, mode: QuizMode) -> None:
        """Create a session.

        Args:
            mode: The strategy that decides the question order.
        """
        self._mode = mode
        self._history: list[AnswerRecord] = []
        self._per_card: dict[str, CardStats] = {}
        self._missed: dict[str, None] = {}

    @property
    def mode(self) -> QuizMode:
        """The active quiz mode."""
        return self._mode

    @property
    def history(self) -> list[AnswerRecord]:
        """A copy of the answers submitted so far, in order."""
        return list(self._history)

    @property
    def total_questions(self) -> int:
        """Number of answers submitted."""
        return len(self._history)

    @property
    def correct_count(self) -> int:
        """Number of correct answers."""
        return sum(1 for record in self._history if record.correct)

    @property
    def accuracy_percent(self) -> float:
        """Percentage of correct answers; ``0.0`` when nothing was asked."""
        return self.stats().accuracy_percent

    @property
    def missed_terms(self) -> list[str]:
        """Unique fronts answered wrong, in order of first miss."""
        return list(self._missed)

    @property
    def per_card(self) -> dict[str, CardStats]:
        """Copy of the attempts and correct counts per card front."""
        return {
            front: CardStats(stats.attempts, stats.correct)
            for front, stats in self._per_card.items()
        }

    def next_card(self) -> Flashcard | None:
        """Return the next card to ask, or ``None`` when finished."""
        return self._mode.next_card()

    def submit(self, card: Flashcard, user_answer: str) -> bool:
        """Score an answer and record it.

        Args:
            card: The card being answered.
            user_answer: The user's raw answer.

        Returns:
            ``True`` if the answer matches, ignoring case and extra whitespace.
        """
        correct = normalize_answer(user_answer) == normalize_answer(card.back)
        self._history.append(AnswerRecord(card.front, user_answer, correct))
        card_stats = self._per_card.setdefault(card.front, CardStats())
        card_stats.attempts += 1
        if correct:
            card_stats.correct += 1
        else:
            self._missed.setdefault(card.front, None)
        self._mode.record_result(card, correct)
        return correct

    def stats(self) -> SessionStats:
        """Return an immutable snapshot of the current results."""
        return SessionStats(
            total_questions=self.total_questions,
            correct_count=self.correct_count,
            missed_terms=tuple(self._missed),
            per_card=self.per_card,
        )
