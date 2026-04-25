"""Tests for the Decision service."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

from objet.entities.card import Card, CardsState
from objet.services.decision import Decision


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
    ) -> None:
        self.cards = cards_state
        self.table = DummyTable(cards_state, pot_amount, buttons)
        self.new_party_detected = new_party_detected
        self.etat = SimpleNamespace(
            cards=cards_state,
            players=self.table.players,
            chance_win=None,
            chance_win_0=None,
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


def test_check_when_call_max_is_below_min_button_value() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0))
    game.etat.Call_max = 1.0
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CHECK"
    assert result.reason == "chance_win_below_fold_threshold"


def test_raise_when_call_max_is_high() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0))
    game.etat.Call_max = 3.0
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "RAISE"
    assert result.reason == "chance_win_between_thresholds"


def test_call_when_call_max_is_close_to_min_button_value() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0))
    game.etat.Call_max = 2.02
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CALL"
    assert result.reason == "chance_win_above_aggressive_threshold"
