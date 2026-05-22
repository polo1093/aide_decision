"""Tests for automatic preflop hero position inference."""
from __future__ import annotations

from types import SimpleNamespace

from objet.entities.buttons import Button, Buttons
from objet.services.position_detector import detect_hero_position


class PlayerStub:
    def __init__(self, etat: str) -> None:
        self.etat = etat

    def is_activate(self) -> bool:
        return self.etat in {"play", "paid"}


def _game(*, street: str = "PREFLOP", states: list[str], buttons=None):
    return SimpleNamespace(
        street=street,
        table=SimpleNamespace(buttons=buttons if buttons is not None else Buttons()),
        etat=SimpleNamespace(players=[PlayerStub(state) for state in states]),
    )


def test_preflop_free_option_detects_big_blind() -> None:
    game = _game(
        states=["fold", "paid", "play", "play", "play"],
        buttons=Buttons(button=[Button(enabled=True, etat="check", value=0.0)]),
    )

    detection = detect_hero_position(game, fallback="BTN")

    assert detection.position == "BB"
    assert detection.reason == "preflop_free_option"


def test_pending_players_after_hero_detect_button() -> None:
    game = _game(states=["fold", "paid", "paid", "play", "fold"])

    detection = detect_hero_position(game, fallback="CO")

    assert detection.position == "BTN"
    assert detection.reason == "pending_after_hero_1"


def test_pending_players_after_hero_detect_cutoff() -> None:
    game = _game(states=["fold", "paid", "play", "play", "fold"])

    detection = detect_hero_position(game, fallback="BTN")

    assert detection.position == "CO"
    assert detection.reason == "pending_after_hero_2"


def test_heads_up_paid_option_detects_small_blind() -> None:
    game = _game(states=["play"])

    detection = detect_hero_position(game, fallback="BTN")

    assert detection.position == "SB"
    assert detection.reason == "heads_up_paid_option"


def test_non_preflop_keeps_fallback() -> None:
    game = _game(street="FLOP", states=["play", "paid"])

    detection = detect_hero_position(game, fallback="CO")

    assert detection.position == "CO"
    assert detection.reason == "not_preflop"
