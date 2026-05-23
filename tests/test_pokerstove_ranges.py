"""Tests for the pyeval7-inspired PokerStove range parser."""
from __future__ import annotations

from objet.services.pokerstove_ranges import (
    expand_handtype_group,
    string_to_combos,
    string_to_tokens,
    token_to_hands,
    validate_string,
)


def test_parser_expands_plus_dash_and_weighted_groups() -> None:
    assert string_to_tokens("TT+, 80%(A8o-ATo)") == [
        ("TT", 1.0),
        ("JJ", 1.0),
        ("QQ", 1.0),
        ("KK", 1.0),
        ("AA", 1.0),
        ("A8o", 0.8),
        ("A9o", 0.8),
        ("ATo", 0.8),
    ]


def test_parser_generates_concrete_combo_counts() -> None:
    assert len(token_to_hands("ATs")) == 4
    assert len(token_to_hands("55")) == 6
    assert len(token_to_hands("74o")) == 12
    assert len(string_to_combos("AKs, AKo")) == 16


def test_parser_validation_matches_pokerstove_errors() -> None:
    assert validate_string("ATs+,KQ, .2(4s9s)") is True
    assert validate_string("AX+") is False
    assert expand_handtype_group(("T7o", "+")) == ["T7o", "T8o", "T9o"]
