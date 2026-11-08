"""Tests for quiz modes (Strategy), the mode factory and quiz scoring."""

from __future__ import annotations

import random
from typing import Sequence

import pytest

import quiz_engine
from data_loader import Flashcard
from quiz_engine import (
    AVAILABLE_MODES,
    REINSERT_GAP,
    AdaptiveMode,
    CardStats,
    QuizMode,
    QuizSession,
    RandomMode,
    SequentialMode,
    create_mode,
    normalize_answer,
)


def _drain(mode: QuizMode) -> list[Flashcard]:
    """Ask every card once (all answered correctly) and return the order."""
    asked: list[Flashcard] = []
    while True:
        card = mode.next_card()
        if card is None:
            return asked
        asked.append(card)
        mode.record_result(card, True)


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------


def test_quiz_mode_factory(cards: list[Flashcard]) -> None:
    """create_mode returns the right Strategy class for every valid name."""
    expected = {
        "sequential": SequentialMode,
        "random": RandomMode,
        "adaptive": AdaptiveMode,
    }
    assert set(AVAILABLE_MODES) == set(expected)

    for name, mode_class in expected.items():
        mode = create_mode(name, cards)
        assert isinstance(mode, mode_class)
        assert isinstance(mode, QuizMode)
        assert mode.name == name

    # Names are case-insensitive and surrounding whitespace is ignored.
    assert isinstance(create_mode("RANDOM", cards), RandomMode)
    assert isinstance(create_mode("  Adaptive ", cards), AdaptiveMode)

    # Unknown names fail with a message listing every valid choice.
    with pytest.raises(ValueError) as info:
        create_mode("zigzag", cards)
    message = str(info.value)
    assert "zigzag" in message
    for name in expected:
        assert name in message

    # The limit option truncates the ordering.
    limited = create_mode("sequential", cards, limit=2)
    assert _drain(limited) == cards[:2]


def test_available_modes_is_sorted_tuple_of_names() -> None:
    """AVAILABLE_MODES is a sorted tuple, usable as argparse choices."""
    assert AVAILABLE_MODES == ("adaptive", "random", "sequential")


@pytest.mark.parametrize("limit", [0, -1])
def test_create_mode_rejects_non_positive_limit(
    cards: list[Flashcard], limit: int
) -> None:
    """A limit below 1 raises ValueError."""
    with pytest.raises(ValueError, match="positive"):
        create_mode("sequential", cards, limit=limit)


@pytest.mark.parametrize("mode_name", ["sequential", "random", "adaptive"])
def test_limit_to_validation_on_every_mode(
    cards: list[Flashcard], mode_name: str
) -> None:
    """limit_to(0) and limit_to(-3) raise ValueError for each mode."""
    mode = create_mode(mode_name, cards)

    for bad in (0, -3):
        with pytest.raises(ValueError):
            mode.limit_to(bad)


def test_limit_larger_than_deck_keeps_all_cards(cards: list[Flashcard]) -> None:
    """A limit above the deck size does not pad or fail."""
    mode = create_mode("sequential", cards, limit=100)

    assert _drain(mode) == cards


# --------------------------------------------------------------------------
# Sequential / Random
# --------------------------------------------------------------------------


def test_sequential_mode_keeps_deck_order(cards: list[Flashcard]) -> None:
    """Sequential mode serves cards in deck order and then finishes."""
    mode = SequentialMode(cards)

    assert _drain(mode) == cards
    assert mode.next_card() is None


def test_sequential_mode_does_not_requeue_wrong_answers(
    cards: list[Flashcard],
) -> None:
    """Wrong answers have no effect on the sequential order."""
    mode = SequentialMode(cards)
    asked = []
    while (card := mode.next_card()) is not None:
        asked.append(card)
        mode.record_result(card, False)

    assert asked == cards


def test_mode_does_not_mutate_input_deck(cards: list[Flashcard]) -> None:
    """Modes copy the deck instead of reordering the caller's list."""
    original = list(cards)

    _drain(RandomMode(cards, random.Random(1)))

    assert cards == original


def test_random_mode_is_deterministic_with_seed(cards: list[Flashcard]) -> None:
    """Two RandomModes seeded alike produce the same order."""
    first = _drain(RandomMode(cards, random.Random(42)))
    second = _drain(RandomMode(cards, random.Random(42)))

    assert first == second


def test_random_mode_is_a_permutation_of_the_deck(cards: list[Flashcard]) -> None:
    """Random mode asks each card exactly once."""
    asked = _drain(RandomMode(cards, random.Random(7)))

    assert sorted(asked, key=lambda c: c.front) == sorted(cards, key=lambda c: c.front)
    assert len(asked) == len(cards)


def test_random_mode_differs_from_deck_order_for_some_seed() -> None:
    """Shuffling really happens: some seed gives a non-deck order."""
    deck = [Flashcard(f"Q{i}", "A") for i in range(10)]

    orders = [_drain(RandomMode(deck, random.Random(seed))) for seed in range(5)]

    assert any(order != deck for order in orders)


def test_random_mode_without_rng_still_serves_all_cards(
    cards: list[Flashcard],
) -> None:
    """With no rng supplied a fresh generator is used."""
    mode = create_mode("random", cards)

    assert len(_drain(mode)) == len(cards)


def test_random_mode_limit_applies_after_shuffle(cards: list[Flashcard]) -> None:
    """The limit keeps the first N cards of the shuffled order."""
    full = _drain(RandomMode(cards, random.Random(3)))

    limited = _drain(create_mode("random", cards, rng=random.Random(3), limit=2))

    assert limited == full[:2]


def test_create_forwards_rng_to_random_mode(cards: list[Flashcard]) -> None:
    """The factory passes the rng so seeded runs are reproducible."""
    first = _drain(create_mode("random", cards, rng=random.Random(5)))
    second = _drain(create_mode("random", cards, rng=random.Random(5)))

    assert first == second


# --------------------------------------------------------------------------
# Adaptive
# --------------------------------------------------------------------------


def test_adaptive_mode_behavior(cards: list[Flashcard]) -> None:
    """A wrong card returns after REINSERT_GAP cards; a right one never does."""
    mode = AdaptiveMode(cards)  # Q1..Q5, no history
    asked: list[str] = []

    first = mode.next_card()
    assert first == cards[0]
    asked.append(first.front)
    mode.record_result(first, False)  # miss Q1

    # Exactly REINSERT_GAP other cards come before Q1 returns.
    for expected in cards[1 : 1 + REINSERT_GAP]:
        card = mode.next_card()
        assert card == expected
        asked.append(card.front)
        mode.record_result(card, True)
    again = mode.next_card()
    assert again == cards[0]
    asked.append(again.front)

    # Answer Q1 correctly now: it must not come back.
    mode.record_result(again, True)
    rest = _drain(mode)
    assert cards[0] not in rest
    assert rest == cards[1 + REINSERT_GAP :]
    assert asked.count("Q1") == 2

    # The deck is finished only once everything was answered correctly.
    assert mode.next_card() is None


def test_adaptive_mode_repeats_until_answered_correctly(
    cards: list[Flashcard],
) -> None:
    """A card missed several times keeps returning until it is right."""
    mode = AdaptiveMode(cards[:2])
    target = cards[0]
    misses = 0
    served: list[Flashcard] = []

    while (card := mode.next_card()) is not None:
        served.append(card)
        is_target_wrong = card == target and misses < 3
        if is_target_wrong:
            misses += 1
        mode.record_result(card, not is_target_wrong)

    assert served.count(target) == 4  # three misses + one success
    assert served.count(cards[1]) == 1


def test_adaptive_mode_deck_finishes_only_after_all_correct(
    cards: list[Flashcard],
) -> None:
    """While any card is unanswered-correctly, next_card keeps returning one."""
    mode = AdaptiveMode(cards)
    for _ in range(len(cards)):
        card = mode.next_card()
        assert card is not None
        mode.record_result(card, False)  # everything wrong

    assert mode.next_card() is not None  # the deck is NOT finished


def test_adaptive_with_fewer_cards_than_gap_requeues_at_end() -> None:
    """With less than REINSERT_GAP cards left, the miss goes to the end."""
    deck = [Flashcard("A", "a"), Flashcard("B", "b")]
    assert len(deck) - 1 < REINSERT_GAP
    mode = AdaptiveMode(deck)

    first = mode.next_card()
    assert first == deck[0]
    mode.record_result(first, False)

    assert mode.next_card() == deck[1]
    mode.record_result(deck[1], True)
    assert mode.next_card() == deck[0]


def test_adaptive_single_card_deck_repeats_until_correct() -> None:
    """A one-card deck re-asks the card immediately after a miss."""
    card = Flashcard("Only", "one")
    mode = AdaptiveMode([card])

    assert mode.next_card() == card
    mode.record_result(card, False)
    assert mode.next_card() == card
    mode.record_result(card, True)
    assert mode.next_card() is None


def test_adaptive_does_not_duplicate_card_already_queued(
    cards: list[Flashcard],
) -> None:
    """Recording a miss twice for a queued card does not queue it twice."""
    mode = AdaptiveMode(cards)
    first = mode.next_card()
    assert first is not None
    mode.record_result(first, False)
    mode.record_result(first, False)

    asked = []
    while (card := mode.next_card()) is not None:
        asked.append(card)
        mode.record_result(card, True)

    assert asked.count(first) == 1


def test_adaptive_miss_counts_put_missed_cards_first(
    cards: list[Flashcard],
) -> None:
    """Historically missed cards come first, most misses first."""
    history = {"Q4": 5, "Q2": 1, "Q5": 3}

    order = _drain(AdaptiveMode(cards, miss_counts=history))

    assert [c.front for c in order] == ["Q4", "Q5", "Q2", "Q1", "Q3"]


def test_adaptive_miss_counts_matched_case_insensitively() -> None:
    """History keys match card fronts ignoring case."""
    deck = [Flashcard("Alpha", "a"), Flashcard("Beta", "b")]

    order = _drain(AdaptiveMode(deck, miss_counts={"BETA": 2}))

    assert [c.front for c in order] == ["Beta", "Alpha"]


def test_adaptive_ties_keep_deck_order(cards: list[Flashcard]) -> None:
    """Cards with equal miss counts stay in deck order (stable sort)."""
    order = _drain(AdaptiveMode(cards, miss_counts={"Q3": 2, "Q5": 2}))

    assert [c.front for c in order] == ["Q3", "Q5", "Q1", "Q2", "Q4"]


def test_create_forwards_miss_counts_to_adaptive_mode(
    cards: list[Flashcard],
) -> None:
    """The factory hands historical misses to AdaptiveMode."""
    mode = create_mode("adaptive", cards, miss_counts={"Q5": 1})

    assert mode.next_card() == cards[4]


def test_miss_counts_are_ignored_by_other_modes(cards: list[Flashcard]) -> None:
    """Sequential mode ignores miss_counts."""
    mode = create_mode("sequential", cards, miss_counts={"Q5": 9})

    assert _drain(mode) == cards


def test_adaptive_limit_applies_after_history_ordering(
    cards: list[Flashcard],
) -> None:
    """--limit keeps the most-missed cards, not just the first in the deck."""
    mode = create_mode("adaptive", cards, miss_counts={"Q5": 4}, limit=2)

    assert [c.front for c in _drain(mode)] == ["Q5", "Q1"]


# --------------------------------------------------------------------------
# Extensibility (Strategy + Factory)
# --------------------------------------------------------------------------


class _ReverseMode(QuizMode):
    """A tiny new strategy: ask the deck backwards."""

    def __init__(self, cards: Sequence[Flashcard]) -> None:
        super().__init__(cards)
        self._remaining = list(reversed(self._cards))

    @property
    def name(self) -> str:
        return "reverse"

    def next_card(self) -> Flashcard | None:
        return self._remaining.pop(0) if self._remaining else None

    def limit_to(self, count: int) -> None:
        if count < 1:
            raise ValueError("limit must be a positive integer")
        del self._remaining[count:]


def test_new_mode_can_be_added_without_touching_the_factory(
    monkeypatch: pytest.MonkeyPatch, cards: list[Flashcard]
) -> None:
    """Registering a new QuizMode subclass makes create_mode able to build it."""
    monkeypatch.setitem(quiz_engine._MODE_REGISTRY, "reverse", _ReverseMode)

    mode = create_mode("Reverse", cards, limit=2)
    session = QuizSession(mode)

    assert isinstance(mode, _ReverseMode)
    assert isinstance(mode, QuizMode)
    first = session.next_card()
    assert first == cards[-1]
    assert session.submit(first, first.back) is True
    assert [session.next_card(), session.next_card()] == [cards[-2], None]


def test_registry_is_restored_after_extensibility_test() -> None:
    """The monkeypatched registry entry does not leak between tests."""
    assert "reverse" not in quiz_engine._MODE_REGISTRY


def test_default_record_result_hook_does_nothing(cards: list[Flashcard]) -> None:
    """The base-class hook is a safe no-op for modes that don't override it."""
    mode = _ReverseMode(cards)

    mode.record_result(cards[0], False)

    assert mode.next_card() == cards[-1]


def test_quiz_mode_is_abstract(cards: list[Flashcard]) -> None:
    """QuizMode cannot be instantiated directly."""
    with pytest.raises(TypeError):
        QuizMode(cards)  # type: ignore[abstract]


# --------------------------------------------------------------------------
# Scoring: normalize_answer / QuizSession
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  Hello   World ", "hello world"),
        ("PARIS", "paris"),
        ("a\tb\nc", "a b c"),
        ("", ""),
        ("STRASSE", "strasse"),
    ],
)
def test_normalize_answer(raw: str, expected: str) -> None:
    """Normalisation trims, collapses whitespace and folds case."""
    assert normalize_answer(raw) == expected


def test_submit_is_case_insensitive_and_ignores_whitespace() -> None:
    """Answers match regardless of case and extra whitespace."""
    card = Flashcard("Capital of France?", "Paris")
    session = QuizSession(SequentialMode([card]))

    assert session.submit(card, "  pARIS ") is True
    assert session.submit(card, "Par is") is False


def test_submit_collapses_internal_whitespace() -> None:
    """Multi-word answers match despite uneven spacing."""
    card = Flashcard("DNS", "Domain Name System")
    session = QuizSession(SequentialMode([card]))

    assert session.submit(card, "domain   name\tsystem") is True


def test_accuracy_is_zero_without_questions() -> None:
    """No questions asked means 0.0 accuracy, not ZeroDivisionError."""
    session = QuizSession(SequentialMode([Flashcard("Q", "A")]))

    assert session.accuracy_percent == 0.0
    assert session.stats().accuracy_percent == 0.0
    assert session.stats().total_questions == 0


def test_session_stats_counts_and_accuracy(cards: list[Flashcard]) -> None:
    """Totals, correct count and accuracy reflect submitted answers."""
    session = QuizSession(SequentialMode(cards))
    for card, answer in zip(cards[:4], ["A1", "wrong", "A3", "wrong"]):
        session.submit(card, answer)

    stats = session.stats()

    assert (stats.total_questions, stats.correct_count) == (4, 2)
    assert stats.accuracy_percent == pytest.approx(50.0)
    assert session.total_questions == 4
    assert session.correct_count == 2


def test_missed_terms_are_unique_and_in_first_miss_order(
    cards: list[Flashcard],
) -> None:
    """A card missed twice is listed once, at its first-miss position."""
    session = QuizSession(SequentialMode(cards))
    session.submit(cards[2], "no")
    session.submit(cards[0], "no")
    session.submit(cards[2], "still no")
    session.submit(cards[1], "A2")

    assert session.missed_terms == ["Q3", "Q1"]
    assert session.stats().missed_terms == ("Q3", "Q1")


def test_per_card_counts_attempts_and_correct(cards: list[Flashcard]) -> None:
    """per_card tracks attempts and correct answers for each front."""
    session = QuizSession(AdaptiveMode(cards))
    session.submit(cards[0], "no")
    session.submit(cards[0], "A1")
    session.submit(cards[1], "A2")

    per_card = session.per_card

    assert per_card["Q1"] == CardStats(attempts=2, correct=1)
    assert per_card["Q2"] == CardStats(attempts=1, correct=1)
    assert "Q3" not in per_card


def test_history_returns_an_immutable_copy(cards: list[Flashcard]) -> None:
    """Mutating the returned history does not change the session."""
    session = QuizSession(SequentialMode(cards))
    session.submit(cards[0], "A1")

    history = session.history
    history.clear()

    assert len(session.history) == 1
    assert session.history[0].front == "Q1"
    assert session.history[0].user_answer == "A1"
    assert session.history[0].correct is True


def test_per_card_returns_a_copy(cards: list[Flashcard]) -> None:
    """Mutating the returned per_card dict does not change the session."""
    session = QuizSession(SequentialMode(cards))
    session.submit(cards[0], "A1")

    snapshot = session.per_card
    snapshot["Q1"].attempts = 99
    snapshot.clear()

    assert session.per_card["Q1"].attempts == 1


def test_history_keeps_raw_user_answer(cards: list[Flashcard]) -> None:
    """The history stores the answer exactly as typed."""
    session = QuizSession(SequentialMode(cards))
    session.submit(cards[0], "  a1  ")

    assert session.history[0].user_answer == "  a1  "
    assert session.history[0].correct is True


def test_session_exposes_mode_and_serves_cards(cards: list[Flashcard]) -> None:
    """The session delegates card selection to its mode."""
    mode = SequentialMode(cards)
    session = QuizSession(mode)

    assert session.mode is mode
    assert session.next_card() == cards[0]


def test_session_feeds_results_back_to_adaptive_mode(
    cards: list[Flashcard],
) -> None:
    """submit() notifies the mode, so a wrong answer is re-queued."""
    session = QuizSession(AdaptiveMode(cards))
    first = session.next_card()
    assert first is not None

    session.submit(first, "wrong")
    seen = [session.next_card() for _ in range(REINSERT_GAP + 1)]

    assert seen[-1] == first
