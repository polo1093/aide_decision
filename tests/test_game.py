"""Tests for Game chronology and new-hand detection."""
from __future__ import annotations

from objet.entities.card import Card, CardsState
from objet.services.game import Game, _monte_carlo_equity


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
    assert game.hand_id == 2


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


def test_empty_scan_pot_drop_does_not_detect_new_party() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 80.0
    _set_visible_cards(game, hero_count=0, board_count=0)

    game.table.pot.amount = 5.0
    assert game._detect_new_party() is False

    assert game.new_party_detected is False
    assert game._pending_new_party_cleanup is False
    assert game._last_pot_amount == 80.0
    assert game.street == "FLOP"


def test_partial_hero_scan_pot_drop_does_not_detect_new_party() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 80.0
    _set_visible_cards(game, hero_count=1, board_count=0)

    game.table.pot.amount = 5.0
    assert game._detect_new_party() is False

    assert game.new_party_detected is False
    assert game._pending_new_party_cleanup is False
    assert game._last_pot_amount == 80.0
    assert game.street == "FLOP"


def test_idle_preflop_scan_initializes_pot_without_warning_path() -> None:
    game = Game()
    game.street = "IDLE"
    game._last_pot_amount = 0.13
    _set_visible_cards(game, hero_count=2, board_count=0)

    game.table.pot.amount = 0.05
    assert game._detect_new_party() is False

    assert game.new_party_detected is False
    assert game._pending_new_party_cleanup is False
    assert game._last_pot_amount == 0.05
    assert game.street == "PREFLOP"


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
    game.table.buttons[0].apply_scan("paie 1.00")
    game.table.players[0].fond.amount = 12.0
    game.table.players[0].fond_start_Party = 20.0
    game.table.players[0].etat = "fold"
    game.table.players[0].active_at_start = False

    assert game._detect_new_party() is True
    game.ack_new_party()

    assert game.new_party_detected is False
    assert game._pending_new_party_cleanup is False
    assert game.street == "IDLE"
    assert game.table.pot.amount is None
    assert game.table.buttons[0].is_activate() is False
    assert game.table.players[0].fond.amount is None
    assert game.table.players[0].fond_start_Party == 0
    assert game.table.players[0].etat == "play"
    assert game.table.players[0].active_at_start is True
    assert all(card.formatted is None for card in game.table.cards.me_cards())
    assert all(card.formatted is None for card in game.table.cards.board_cards())


def test_partial_flop_scan_does_not_update_stable_board_or_crash() -> None:
    game = Game()
    game.etat.cards.me[0].apply_observation("A", "hearts")
    game.etat.cards.me[1].apply_observation("K", "diamonds")

    scanned = CardsState()
    scanned.me[0].apply_observation("A", "hearts")
    scanned.me[1].apply_observation("K", "diamonds")
    scanned.board[0].apply_observation("8", "spades")
    scanned.board[1].apply_observation("K", "spades")

    game.etat.update(
        cards_state=scanned,
        players=game.table.players,
        pot=0.10,
    )

    assert [card.formatted for card in game.etat.cards.board_cards()] == [
        None,
        None,
        None,
        None,
        None,
    ]
    assert game.etat.chance_win_0 is not None


def test_monte_carlo_equity_uses_multiple_opponents() -> None:
    hero = [Card(), Card()]
    hero[0].apply_observation("A", "hearts")
    hero[1].apply_observation("K", "diamonds")

    equity_one = _monte_carlo_equity(
        hero_cards=[card.poker_card for card in hero],
        board_cards=[],
        opponent_count=1,
        simulations=500,
    )
    equity_many = _monte_carlo_equity(
        hero_cards=[card.poker_card for card in hero],
        board_cards=[],
        opponent_count=4,
        simulations=500,
    )

    assert 0 <= equity_many <= equity_one <= 1


def test_update_uses_to_call_for_ev_and_required_equity() -> None:
    game = Game()
    game.etat.monte_carlo_simulations = 200

    scanned = CardsState()
    scanned.me[0].apply_observation("A", "hearts")
    scanned.me[1].apply_observation("K", "diamonds")

    game.etat.update(
        cards_state=scanned,
        players=game.table.players,
        pot=0.10,
        to_call=0.05,
    )

    assert game.etat.to_call == 0.05
    assert abs(game.etat.equity_required - (0.05 / 0.15)) < 1e-12
    assert game.etat.chance_win is not None
