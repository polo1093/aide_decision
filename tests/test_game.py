"""Tests for Game chronology and new-hand detection."""
from __future__ import annotations

from objet.entities.card import Card, CardsState
from objet.services.game import Game


class SpyEtat:
    def __init__(self) -> None:
        self.update_called = False

    def update(self, **_) -> None:
        self.update_called = True


def _set_visible_cards(game: Game, *, hero_count: int, board_count: int) -> None:
    me = [Card(formatted="hero") if index < hero_count else Card() for index in range(2)]
    board = [Card(formatted="board") if index < board_count else Card() for index in range(5)]
    game.table.cards = CardsState(board=board, me=me)


def test_missing_pot_does_not_clear_last_valid_pot() -> None:
    game = Game()
    _set_visible_cards(game, hero_count=2, board_count=0)

    game.table.pot.amount = 10.0
    assert game._detect_new_party() is False

    game.table.pot.amount = None
    assert game._detect_new_party() is None

    assert game._last_pot_amount == 10.0
    assert game.new_party_detected is False


def test_pot_drop_without_card_reduction_does_not_detect_new_party() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 100.0
    _set_visible_cards(game, hero_count=2, board_count=3)

    game.table.pot.amount = 60.0
    assert game._detect_new_party() is False

    assert game.new_party_detected is False
    assert game._last_pot_amount == 100.0


def test_preflop_pot_drop_detects_new_party_without_card_reduction() -> None:
    game = Game()
    game.street = "PREFLOP"
    game._last_pot_amount = 100.0
    _set_visible_cards(game, hero_count=2, board_count=0)

    game.table.pot.amount = 60.0
    assert game._detect_new_party() is True

    assert game.new_party_detected is True
    assert game._last_pot_amount == 60.0


def test_noisy_pot_drop_is_discarded_when_pot_recovers() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 100.0
    _set_visible_cards(game, hero_count=2, board_count=3)

    game.table.pot.amount = 60.0
    assert game._detect_new_party() is False

    game.table.pot.amount = 105.0
    assert game._detect_new_party() is False

    assert game._last_pot_amount == 105.0

    game.table.pot.amount = 60.0
    assert game._detect_new_party() is False


def test_pot_drop_with_card_reduction_detects_new_party_immediately() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 80.0
    _set_visible_cards(game, hero_count=2, board_count=0)

    game.table.pot.amount = 5.0
    assert game._detect_new_party() is True

    assert game.new_party_detected is True
    assert game.street == "PREFLOP"
    assert game._pending_new_party_cleanup is True


def test_street_does_not_regress_without_new_party() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 20.0
    _set_visible_cards(game, hero_count=2, board_count=0)

    game.table.pot.amount = 25.0
    assert game._detect_new_party() is False

    assert game.street == "FLOP"


def test_update_from_scan_skips_state_update_when_new_party_detected() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 80.0
    _set_visible_cards(game, hero_count=2, board_count=0)
    game.table.pot.amount = 5.0
    game.etat = SpyEtat()

    assert game.update_from_scan() is True

    assert game.etat.update_called is False


def test_ack_new_party_resets_flags_and_street() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 80.0
    _set_visible_cards(game, hero_count=2, board_count=0)
    game.table.pot.amount = 5.0

    assert game._detect_new_party() is True
    game.ack_new_party()

    assert game.new_party_detected is False
    assert game._pending_new_party_cleanup is False
    assert game.street == "IDLE"
    assert all(card.formatted is None for card in game.table.cards.me_cards())
    assert all(card.formatted is None for card in game.table.cards.board_cards())
