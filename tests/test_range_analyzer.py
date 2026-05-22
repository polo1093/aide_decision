"""Tests for imported range-analyzer helpers."""
from __future__ import annotations

from objet.entities.card import Card
from objet.services.range_analyzer import (
    classify_hole_cards,
    get_hand_action,
    get_range_percentage,
    is_hand_in_range,
    normalize_position,
)


def _cards(*values: tuple[str, str]):
    out = []
    for value, suit in values:
        card = Card()
        card.apply_observation(value, suit)
        out.append(card.poker_card)
    return out


def test_classify_hole_cards_uses_imported_range_notation() -> None:
    assert classify_hole_cards(_cards(("A", "hearts"), ("K", "hearts"))) == "AKs"
    assert classify_hole_cards(_cards(("10", "clubs"), ("10", "diamonds"))) == "TT"
    assert classify_hole_cards(_cards(("Q", "spades"), ("J", "diamonds"))) == "QJo"


def test_position_aliases_and_missing_hands_default_to_fold() -> None:
    assert normalize_position("button") == "BTN"
    assert get_hand_action("button", "76s").raise_frequency == 100
    assert get_hand_action("UTG", "72o").fold_frequency == 100
    assert is_hand_in_range("UTG", "72o") is False


def test_late_position_range_is_wider_than_early_position_range() -> None:
    assert get_range_percentage("BTN") > get_range_percentage("UTG")
