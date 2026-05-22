"""Tests for the Decision service."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest

from objet.entities.buttons import Button, Buttons
from objet.entities.card import Card, CardsState
from objet.services.decision import Decision, DecisionConfig


class DummyPlayer:
    def __init__(self, fond_amount: float) -> None:
        self.fond = SimpleNamespace(amount=fond_amount)
        self.fond_start_Party = fond_amount
        self.active_at_start = True
        self.etat = "play"

    def is_activate(self) -> bool:
        return True


class DummyPlayers:
    def __init__(self) -> None:
        self._players = [DummyPlayer(100.0), DummyPlayer(80.0)]
        self.nbr_player_active = len(self._players)
        self.nbr_player_start = len(self._players)

    def __len__(self) -> int:
        return len(self._players)

    def __getitem__(self, index: int) -> DummyPlayer:
        return self._players[index]

    def __iter__(self):
        return iter(self._players)


class DummyButtons:
    def __init__(self, *, min_value: float = 1.0, active: bool = True) -> None:
        self._min_value = min_value
        self._active = active

    def one_is_activate(self) -> bool:
        return self._active

    def min_value(self) -> float:
        return self._min_value


class DummyTable:
    def __init__(
        self,
        cards_state: CardsState,
        pot_amount: Optional[float] = 50.0,
        buttons: Optional[DummyButtons] = None,
    ) -> None:
        self.cards = cards_state
        self.players = DummyPlayers()
        self.pot = None if pot_amount is None else SimpleNamespace(amount=pot_amount)
        self.buttons = buttons if buttons is not None else DummyButtons()


class DummyGame:
    def __init__(
        self,
        cards_state: CardsState,
        *,
        pot_amount: Optional[float] = 50.0,
        buttons: Optional[DummyButtons] = None,
        new_party_detected: bool = False,
        street: str = "PREFLOP",
    ) -> None:
        self.cards = cards_state
        self.table = DummyTable(cards_state, pot_amount, buttons)
        self.new_party_detected = new_party_detected
        self.street = street
        self.etat = SimpleNamespace(
            cards=cards_state,
            players=self.table.players,
            chance_win=None,
            chance_win_0=None,
            equity_required=None,
            pot=pot_amount,
            montant_a_jouer=None,
            Call_max=0.0,
        )


def _cards_state(first: Optional[str], second: Optional[str]) -> CardsState:
    board = [Card() for _ in range(5)]
    me = [
        Card(formatted=first, poker_card=object() if first else None),
        Card(formatted=second, poker_card=object() if second else None),
    ]
    return CardsState(board=board, me=me)


def _cards_state_with_board(
    first: str,
    second: str,
    board_values: list[tuple[str, str]],
) -> CardsState:
    state = _cards_state(None, None)
    state.me[0].apply_observation(first[:-1], _suit_name(first[-1]))
    state.me[1].apply_observation(second[:-1], _suit_name(second[-1]))
    for card, (value, suit) in zip(state.board, board_values):
        card.apply_observation(value, suit)
    return state


def _suit_name(symbol: str) -> str:
    return {
        "S": "spades",
        "H": "hearts",
        "D": "diamonds",
        "C": "clubs",
    }[symbol]


def _game_with_cards(first: Optional[str], second: Optional[str]) -> DummyGame:
    return DummyGame(_cards_state(first, second))


def test_wait_when_hero_cards_missing() -> None:
    game = _game_with_cards("AS", None)
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "WAIT"
    assert result.reason == "hero_cards_not_detected_yet"


def test_wait_when_new_party_is_pending_reset() -> None:
    game = DummyGame(_cards_state("AS", "KS"), new_party_detected=True)
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "WAIT"
    assert result.reason == "new_party_pending_reset"


def test_wait_when_no_button_is_active() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(active=False))
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "WAIT"
    assert result.reason == "not_buttons"


def test_fold_when_call_is_not_profitable() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0))
    game.etat.Call_max = 1.0
    game.etat.chance_win = 0.20
    game.etat.equity_required = 0.35
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "FOLD"
    assert result.reason == "negative_call_ev"


def test_call_when_edge_is_positive_but_not_strong_enough_to_raise() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0))
    game.etat.Call_max = 10.0
    game.etat.chance_win = 0.50
    game.etat.equity_required = 0.35
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CALL"
    assert result.reason == "call_profitable_or_close"


def test_raise_when_paid_pot_has_very_strong_equity_and_edge() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0), street="TURN")
    game.etat.Call_max = 40.0
    game.etat.chance_win = 0.88
    game.etat.equity_required = 0.45
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "RAISE"
    assert result.reason == "positive_edge_raise"
    assert result.raise_amount == 30.0


def test_raise_small_flop_bet_for_value_and_protection() -> None:
    game = DummyGame(_cards_state("KS", "QS"), buttons=DummyButtons(min_value=20.0), street="FLOP", pot_amount=140.0)
    game.etat.Call_max = 90.0
    game.etat.montant_a_jouer = 90.0
    game.etat.chance_win = 0.58
    game.etat.equity_required = 0.13
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "RAISE"
    assert result.reason == "small_bet_value_protection"
    assert result.raise_amount == 90.0


def test_calls_small_turn_bet_when_equity_is_only_medium() -> None:
    game = DummyGame(_cards_state("KS", "QS"), buttons=DummyButtons(min_value=20.0), street="TURN", pot_amount=180.0)
    game.etat.Call_max = 80.0
    game.etat.chance_win = 0.54
    game.etat.equity_required = 0.10
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CALL"
    assert result.reason == "call_profitable_or_close"


def test_river_small_bet_does_not_trigger_protection_raise() -> None:
    game = DummyGame(_cards_state("KS", "QS"), buttons=DummyButtons(min_value=20.0), street="RIVER", pot_amount=260.0)
    game.etat.Call_max = 120.0
    game.etat.chance_win = 0.65
    game.etat.equity_required = 0.08
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CALL"
    assert result.reason == "call_profitable_or_close"


def test_folds_river_big_bet_when_showdown_equity_is_weak() -> None:
    game = DummyGame(_cards_state("KH", "9S"), buttons=DummyButtons(min_value=80.0), street="RIVER", pot_amount=100.0)
    game.etat.Call_max = 120.0
    game.etat.chance_win = 0.55
    game.etat.chance_win_0 = 0.52
    game.etat.equity_required = 0.44
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "FOLD"
    assert result.reason == "river_big_bet_weak_showdown"


def test_river_paid_raise_requires_near_nut_equity() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0), street="RIVER")
    game.etat.Call_max = 40.0
    game.etat.chance_win = 0.86
    game.etat.equity_required = 0.35
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CALL"
    assert result.reason == "call_profitable_or_close"


def test_folds_river_big_bet_when_hero_only_plays_the_board() -> None:
    cards = _cards_state_with_board(
        "2H",
        "3H",
        [
            ("Q", "diamonds"),
            ("5", "clubs"),
            ("K", "clubs"),
            ("Q", "clubs"),
            ("K", "spades"),
        ],
    )
    game = DummyGame(cards, buttons=DummyButtons(min_value=2080.0), street="RIVER", pot_amount=480.0)
    game.etat.Call_max = 4000.0
    game.etat.chance_win = 0.70
    game.etat.equity_required = 0.20
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "FOLD"
    assert result.reason == "river_board_only_big_bet"


def test_call_when_edge_is_close() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0))
    game.etat.Call_max = 3.0
    game.etat.chance_win = 0.38
    game.etat.equity_required = 0.35
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CALL"
    assert result.reason == "call_profitable_or_close"


def test_no_check_recommendation_without_check_button_when_amount_missing() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="relance", value=0.0),
            Button(enabled=True, etat="paie", value=0.0),
            Button(enabled=True, etat="fold", value=0.0),
        ]
    )
    game = DummyGame(_cards_state("J♦", "10♦"), buttons=buttons)
    game.etat.chance_win = 0.76
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "WAIT"
    assert result.reason == "call_amount_not_detected"


def test_does_not_fold_free_action_when_check_ocr_is_missing_but_bet_button_is_visible() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="fold", value=0.0),
            Button(enabled=True, etat="mise", value=120.0),
        ]
    )
    game = DummyGame(_cards_state("J♦", "10♦"), buttons=buttons)
    game.etat.Call_max = 0.0
    game.etat.chance_win = 0.10
    game.etat.equity_required = 0.50
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "WAIT"
    assert result.reason == "call_amount_not_detected"


def test_paid_position_with_no_check_uses_call_amount() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="relance", value=4760.0),
            Button(enabled=True, etat="paie", value=4520.0),
            Button(enabled=True, etat="fold", value=0.0),
        ]
    )
    game = DummyGame(_cards_state("J♦", "10♦"), buttons=buttons)
    game.etat.Call_max = 322.0
    game.etat.chance_win = 0.244
    game.etat.equity_required = 0.5
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "FOLD"
    assert result.reason == "negative_call_ev"


def test_check_when_action_is_free_and_equity_is_not_strong() -> None:
    buttons = Buttons(button=[Button(enabled=True, etat="check", value=0.0)])
    game = DummyGame(_cards_state("AS", "KS"), buttons=buttons)
    game.etat.chance_win = 0.40
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CHECK"
    assert result.reason == "free_option_no_call_needed"


def test_raise_when_action_is_free_and_equity_is_strong() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="check", value=0.0),
            Button(enabled=True, etat="mise", value=0.02),
        ]
    )
    game = DummyGame(_cards_state("AS", "KS"), buttons=buttons)
    game.etat.chance_win = 0.70
    game.etat.montant_a_jouer = 12.0
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "RAISE"
    assert result.reason == "free_option_strong_equity"
    assert result.raise_amount == 30.0


def test_raise_amount_uses_pot_sizing_instead_of_call_max_cap() -> None:
    game = DummyGame(_cards_state("KS", "QS"), buttons=DummyButtons(min_value=20.0), street="FLOP", pot_amount=280.0)
    game.etat.Call_max = 1000.0
    game.etat.montant_a_jouer = 1000.0
    game.etat.chance_win = 0.80
    game.etat.equity_required = 0.10
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "RAISE"
    assert result.raise_amount == 180.0


def test_check_button_prevents_fold_when_bet_button_is_also_visible() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="check", value=0.0),
            Button(enabled=True, etat="mise", value=0.02),
        ]
    )
    game = DummyGame(_cards_state("AS", "KS"), buttons=buttons)
    game.etat.Call_max = 0.0
    game.etat.chance_win = 0.20
    game.etat.equity_required = 0.35
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CHECK"
    assert result.reason == "free_option_no_call_needed"


def test_check_is_recommended_when_no_raise_button_exists_even_with_strong_equity() -> None:
    buttons = Buttons(button=[Button(enabled=True, etat="check", value=0.0)])
    game = DummyGame(_cards_state("AS", "KS"), buttons=buttons)
    game.etat.chance_win = 0.70
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CHECK"
    assert result.reason == "free_option_no_call_needed"


def test_default_decision_config_keeps_legacy_mode() -> None:
    decision = Decision()

    assert decision.config == DecisionConfig()
    assert decision.config.mode == "legacy"


def test_range_analyzer_is_not_a_standalone_decision_mode() -> None:
    with pytest.raises(ValueError):
        Decision(mode="range_analyzer")  # type: ignore[arg-type]


def test_legacy_uses_range_preflop_when_equity_is_not_ready() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="check", value=0.0),
            Button(enabled=True, etat="mise", value=40.0),
        ]
    )
    game = DummyGame(_cards_state_with_board("7S", "6S", []), buttons=buttons, street="PREFLOP", pot_amount=120.0)
    game.range_position = "BTN"
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "RAISE"
    assert result.reason == "range_analyzer_preflop_open"


def test_legacy_can_fold_clear_preflop_out_of_range_before_equity_is_ready() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="paie", value=20.0),
            Button(enabled=True, etat="fold", value=0.0),
        ]
    )
    game = DummyGame(_cards_state_with_board("7S", "2D", []), buttons=buttons, street="PREFLOP", pot_amount=120.0)
    game.range_position = "UTG"
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "FOLD"
    assert result.reason == "range_analyzer_preflop_out_of_range"


def test_legacy_raises_premium_preflop_even_when_multiway_equity_is_below_paid_raise_threshold() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="relance", value=830.0),
            Button(enabled=True, etat="paie", value=10.0),
            Button(enabled=True, etat="fold", value=0.0),
        ]
    )
    game = DummyGame(_cards_state_with_board("AS", "AD", []), buttons=buttons, street="PREFLOP", pot_amount=90.0)
    game.etat.Call_max = 110.0
    game.etat.chance_win = 0.55
    game.etat.equity_required = 0.10
    game.range_position = "BTN"
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "RAISE"
    assert result.reason == "range_analyzer_preflop_value_raise"
    assert result.raise_amount == 40.0


def test_waits_instead_of_folding_premium_preflop_when_call_amount_is_suspicious() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="relance", value=4640.0),
            Button(enabled=True, etat="paie", value=4320.0),
            Button(enabled=True, etat="fold", value=0.0),
        ]
    )
    game = DummyGame(_cards_state_with_board("KH", "AH", []), buttons=buttons, street="PREFLOP", pot_amount=480.0)
    game.etat.Call_max = 184.0
    game.etat.chance_win = 0.278
    game.etat.equity_required = 0.90
    game.range_position = "BTN"
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "WAIT"
    assert result.reason == "preflop_premium_call_amount_suspicious"


def test_legacy_still_waits_for_equity_after_preflop() -> None:
    game = DummyGame(
        _cards_state_with_board("AS", "KS", [("A", "hearts"), ("7", "clubs"), ("2", "spades")]),
        buttons=DummyButtons(min_value=20.0),
        street="FLOP",
        pot_amount=160.0,
    )
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "WAIT"
    assert result.reason == "equity_not_ready"


def test_pokermaster_mode_folds_paid_river_with_only_medium_equity() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=120.0), street="RIVER", pot_amount=180.0)
    game.etat.Call_max = 500.0
    game.etat.chance_win = 0.68
    game.etat.equity_required = 0.40
    decision = Decision(mode="pokermaster")

    result = decision.decide(game)

    assert result.action == "FOLD"
    assert result.reason == "pokermaster_river_pressure"


def test_pokermaster_mode_raises_only_with_aggressive_button_and_strong_equity() -> None:
    buttons = Buttons(button=[Button(enabled=True, etat="paie", value=20.0)])
    game = DummyGame(_cards_state("AS", "KS"), buttons=buttons, street="TURN", pot_amount=180.0)
    game.etat.Call_max = 500.0
    game.etat.chance_win = 0.92
    game.etat.equity_required = 0.10
    decision = Decision(mode="pokermaster")

    result = decision.decide(game)

    assert result.action == "CALL"
    assert result.reason == "call_profitable_or_close"


def test_pokermaster_mode_raises_strong_paid_turn_when_aggressive_button_exists() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="paie", value=20.0),
            Button(enabled=True, etat="relance", value=60.0),
        ]
    )
    game = DummyGame(_cards_state("AS", "KS"), buttons=buttons, street="TURN", pot_amount=180.0)
    game.etat.Call_max = 500.0
    game.etat.chance_win = 0.92
    game.etat.equity_required = 0.10
    decision = Decision(mode="pokermaster")

    result = decision.decide(game)

    assert result.action == "RAISE"
    assert result.reason == "pokermaster_paid_value_raise"
    assert result.raise_amount == 120.0


def test_pokermaster_mode_checks_free_medium_equity() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="check", value=0.0),
            Button(enabled=True, etat="mise", value=20.0),
        ]
    )
    game = DummyGame(_cards_state("AS", "KS"), buttons=buttons, street="FLOP", pot_amount=120.0)
    game.etat.chance_win = 0.60
    decision = Decision(mode="pokermaster")

    result = decision.decide(game)

    assert result.action == "CHECK"
    assert result.reason == "free_option_no_call_needed"


def test_pokermaster_mode_does_not_bluff_weak_free_hand() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="check", value=0.0),
            Button(enabled=True, etat="mise", value=20.0),
        ]
    )
    game = DummyGame(_cards_state("7S", "2D"), buttons=buttons, street="FLOP", pot_amount=120.0)
    game.etat.chance_win = 0.30
    decision = Decision(mode="pokermaster")

    result = decision.decide(game)

    assert result.action == "CHECK"
    assert result.reason == "free_option_no_call_needed"


def test_pokermaster_short_stack_preflop_folds_weak_late_call() -> None:
    buttons = Buttons(button=[Button(enabled=True, etat="paie", value=320.0)])
    game = DummyGame(_cards_state_with_board("7S", "2D", []), buttons=buttons, street="PREFLOP", pot_amount=960.0)
    game.etat.Call_max = 5000.0
    game.etat.chance_win = 0.55
    game.etat.equity_required = 0.25
    decision = Decision(mode="pokermaster")

    result = decision.decide(game)

    assert result.action == "FOLD"
    assert result.reason == "pokermaster_short_stack_preflop_fold"


def test_pokermaster_short_stack_preflop_raises_premium_with_raise_button() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="paie", value=320.0),
            Button(enabled=True, etat="relance", value=640.0),
        ]
    )
    game = DummyGame(_cards_state_with_board("AS", "AD", []), buttons=buttons, street="PREFLOP", pot_amount=960.0)
    game.etat.Call_max = 5000.0
    game.etat.chance_win = 0.86
    game.etat.equity_required = 0.25
    decision = Decision(mode="pokermaster")

    result = decision.decide(game)

    assert result.action == "RAISE"
    assert result.reason == "pokermaster_short_stack_preflop_pressure"


def test_pokermaster_folds_medium_flop_draw_under_late_tournament_pressure() -> None:
    buttons = Buttons(button=[Button(enabled=True, etat="paie", value=1320.0)])
    game = DummyGame(
        _cards_state_with_board(
            "10S",
            "7S",
            [("6", "spades"), ("5", "spades"), ("J", "hearts")],
        ),
        buttons=buttons,
        street="FLOP",
        pot_amount=5120.0,
    )
    game.etat.Call_max = 5000.0
    game.etat.chance_win = 0.50
    game.etat.equity_required = 0.21
    decision = Decision(mode="pokermaster")

    result = decision.decide(game)

    assert result.action == "FOLD"
    assert result.reason == "pokermaster_postflop_tournament_pressure"
