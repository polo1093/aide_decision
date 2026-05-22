"""Decision helper to recommend a poker action for the hero."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from objet.services.game import Game
from objet.services.equity import starting_hand_strength
from objet.utils.logging_config import get_logger

ActionType = Literal["WAIT", "FOLD", "CALL", "CHECK", "RAISE"]
LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class DecisionResult:
    """Immutable result describing the recommended poker action."""

    action: ActionType
    reason: str
    raise_amount: Optional[float] = None


@dataclass(frozen=True)
class DecisionConfig:
    """Runtime configuration for the decision engine."""

    mode: Literal["legacy", "pokermaster"] = "legacy"


class Decision:
    """Simple, fail-fast decision engine for the hero."""

    # Monte Carlo has variance, so a tiny positive edge is not enough to raise.
    FOLD_EDGE: float = -0.03
    RAISE_EDGE: float = 0.08
    PAID_RAISE_EDGE: float = 0.22
    FREE_RAISE_EQUITY: float = 0.65
    FREE_RAISE_EQUITY_BY_STREET = {
        "PREFLOP": 0.70,
        "FLOP": 0.72,
        "TURN": 0.76,
        "RIVER": 0.82,
    }
    PAID_RAISE_EQUITY_BY_STREET = {
        "PREFLOP": 0.78,
        "FLOP": 0.80,
        "TURN": 0.84,
        "RIVER": 0.90,
    }
    SMALL_BET_MAX_POT_RATIO: float = 0.25
    SMALL_BET_RAISE_EDGE: float = 0.18
    SMALL_BET_RAISE_EQUITY_BY_STREET = {
        "FLOP": 0.54,
        "TURN": 0.58,
    }
    RIVER_BIG_BET_MIN_POT_RATIO: float = 0.55
    RIVER_BIG_BET_MIN_1V1_EQUITY: float = 0.62

    POKERMASTER_FREE_RAISE_EQUITY_BY_STREET = {
        "PREFLOP": 0.74,
        "FLOP": 0.74,
        "TURN": 0.78,
        "RIVER": 0.84,
    }
    POKERMASTER_PAID_RAISE_EQUITY_BY_STREET = {
        "PREFLOP": 0.82,
        "FLOP": 0.84,
        "TURN": 0.88,
        "RIVER": 0.94,
    }
    POKERMASTER_PAID_RAISE_EDGE: float = 0.24
    POKERMASTER_RIVER_PRESSURE_POT_RATIO: float = 0.62
    POKERMASTER_RIVER_PRESSURE_MIN_EQUITY: float = 0.72
    POKERMASTER_LATE_STAGE_MIN_CALL: float = 240.0
    POKERMASTER_LATE_STAGE_MIN_POT: float = 720.0
    POKERMASTER_PREFLOP_SHOVE_STRENGTH: float = 0.72
    POKERMASTER_PREFLOP_CALL_STRENGTH: float = 0.50
    POKERMASTER_POSTFLOP_PRESSURE_EQUITY_BY_STREET = {
        "FLOP": 0.54,
        "TURN": 0.60,
        "RIVER": 0.72,
    }

    def __init__(
        self,
        config: Optional[DecisionConfig] = None,
        *,
        mode: Optional[Literal["legacy", "pokermaster"]] = None,
    ) -> None:
        if config is not None and mode is not None:
            raise ValueError("Use either config or mode, not both.")
        if config is None:
            config = DecisionConfig(mode=mode or "legacy")
        if config.mode not in ("legacy", "pokermaster"):
            raise ValueError(f"Mode de decision inconnu: {config.mode!r}")
        self.config = config

    def decide(self, game: Game) -> DecisionResult:
        """Return the recommended action for the hero based on the current state."""
        if getattr(game, "new_party_detected", False):
            return _log_decision(DecisionResult(action="WAIT", reason="new_party_pending_reset"))

        if not game.etat.cards.is_ready_for_cal():
            return _log_decision(DecisionResult(action="WAIT", reason="hero_cards_not_detected_yet"))

        buttons = getattr(game.table, "buttons", None)
        if buttons is None or not buttons.one_is_activate():
            return _log_decision(DecisionResult(action="WAIT", reason="not_buttons"))

        free_action = _free_action_available(buttons)
        aggressive_action = _aggressive_action_available(buttons)
        to_call = 0.0 if free_action else buttons.min_value()
        equity = getattr(game.etat, "chance_win", None)
        equity_required = getattr(game.etat, "equity_required", None)
        call_max = getattr(game.etat, "Call_max", 0.0)
        if equity is None:
            return _log_decision(DecisionResult(action="WAIT", reason="equity_not_ready"))

        # No money to add: never CALL. Check weak/medium hands, raise strong ones.
        if to_call <= 0:
            if self.config.mode == "pokermaster":
                return self._decide_pokermaster_free_action(
                    game,
                    buttons=buttons,
                    equity=equity,
                    free_action=free_action,
                    aggressive_action=aggressive_action,
                )
            if free_action and aggressive_action and equity >= self._free_raise_equity_threshold(game):
                return _log_decision(
                    DecisionResult(
                        action="RAISE",
                        reason="free_option_strong_equity",
                        raise_amount=_recommended_raise_amount(game, buttons),
                    )
                )
            if free_action:
                return _log_decision(DecisionResult(action="CHECK", reason="free_option_no_call_needed"))
            if _has_explicit_active_buttons(buttons):
                return _log_decision(DecisionResult(action="WAIT", reason="call_amount_not_detected"))
            return _log_decision(DecisionResult(action="CHECK", reason="free_option_no_call_needed"))

        if equity_required is None:
            return _log_decision(DecisionResult(action="WAIT", reason="equity_required_not_ready"))

        edge = equity - equity_required
        LOGGER.debug(
            "DECISION contexte equity=%s equity_required=%s edge=%s call_max=%s to_call=%s",
            equity,
            equity_required,
            edge,
            call_max,
            to_call,
        )

        if call_max < to_call or edge < self.FOLD_EDGE:
            return _log_decision(DecisionResult(action="FOLD", reason="negative_call_ev"))

        if self.config.mode == "pokermaster":
            return self._decide_pokermaster_paid_action(
                game,
                buttons=buttons,
                equity=equity,
                edge=edge,
                to_call=to_call,
                aggressive_action=aggressive_action,
            )

        if self._should_fold_river_board_only_hand(game, to_call=to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="river_board_only_big_bet"))

        if self._should_fold_river_big_bet_with_weak_showdown(game, to_call=to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="river_big_bet_weak_showdown"))

        if self._can_value_raise_paid_pot(game, equity=equity, edge=edge):
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="positive_edge_raise",
                    raise_amount=_recommended_raise_amount(game, buttons),
                )
            )

        if self._can_raise_small_bet_for_value(game, equity=equity, edge=edge, to_call=to_call):
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="small_bet_value_protection",
                    raise_amount=_recommended_raise_amount(game, buttons),
                )
            )
        
        return _log_decision(DecisionResult(action="CALL", reason="call_profitable_or_close"))

    def _decide_pokermaster_free_action(
        self,
        game: Game,
        *,
        buttons,
        equity: float,
        free_action: bool,
        aggressive_action: bool,
    ) -> DecisionResult:
        if (
            _game_street(game) == "PREFLOP"
            and aggressive_action
            and self._pokermaster_late_stage_pressure(game, to_call=0.0)
            and self._hero_preflop_strength(game) >= self.POKERMASTER_PREFLOP_SHOVE_STRENGTH
        ):
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="pokermaster_short_stack_preflop_pressure",
                    raise_amount=_recommended_raise_amount(game, buttons),
                )
            )

        if free_action and aggressive_action and equity >= self._pokermaster_free_raise_equity_threshold(game):
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="pokermaster_free_value_raise",
                    raise_amount=_recommended_raise_amount(game, buttons),
                )
            )
        if free_action:
            return _log_decision(DecisionResult(action="CHECK", reason="free_option_no_call_needed"))
        if _has_explicit_active_buttons(buttons):
            return _log_decision(DecisionResult(action="WAIT", reason="call_amount_not_detected"))
        return _log_decision(DecisionResult(action="CHECK", reason="free_option_no_call_needed"))

    def _decide_pokermaster_paid_action(
        self,
        game: Game,
        *,
        buttons,
        equity: float,
        edge: float,
        to_call: float,
        aggressive_action: bool,
    ) -> DecisionResult:
        short_stack_preflop = self._decide_pokermaster_short_stack_preflop(
            game,
            buttons=buttons,
            to_call=to_call,
            aggressive_action=aggressive_action,
        )
        if short_stack_preflop is not None:
            return short_stack_preflop

        if self._pokermaster_should_fold_postflop_tournament_pressure(game, equity=equity, to_call=to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="pokermaster_postflop_tournament_pressure"))

        if self._should_fold_river_board_only_hand(game, to_call=to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="river_board_only_big_bet"))

        if self._should_fold_river_big_bet_with_weak_showdown(game, to_call=to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="river_big_bet_weak_showdown"))

        if self._pokermaster_should_fold_river_pressure(game, equity=equity, to_call=to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="pokermaster_river_pressure"))

        if aggressive_action and self._can_pokermaster_value_raise_paid_pot(game, equity=equity, edge=edge):
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="pokermaster_paid_value_raise",
                    raise_amount=_recommended_raise_amount(game, buttons),
                )
            )

        return _log_decision(DecisionResult(action="CALL", reason="call_profitable_or_close"))

    def _free_raise_equity_threshold(self, game: Game) -> float:
        street = _game_street(game)
        return self.FREE_RAISE_EQUITY_BY_STREET.get(street, self.FREE_RAISE_EQUITY)

    def _can_value_raise_paid_pot(self, game: Game, *, equity: float, edge: float) -> bool:
        if edge < max(self.RAISE_EDGE, self.PAID_RAISE_EDGE):
            return False
        street = _game_street(game)
        threshold = self.PAID_RAISE_EQUITY_BY_STREET.get(street, 0.84)
        return equity >= threshold

    def _can_pokermaster_value_raise_paid_pot(self, game: Game, *, equity: float, edge: float) -> bool:
        if edge < self.POKERMASTER_PAID_RAISE_EDGE:
            return False
        street = _game_street(game)
        threshold = self.POKERMASTER_PAID_RAISE_EQUITY_BY_STREET.get(street, 0.88)
        return equity >= threshold

    def _decide_pokermaster_short_stack_preflop(
        self,
        game: Game,
        *,
        buttons,
        to_call: float,
        aggressive_action: bool,
    ) -> Optional[DecisionResult]:
        if _game_street(game) != "PREFLOP" or not self._pokermaster_late_stage_pressure(game, to_call=to_call):
            return None

        strength = self._hero_preflop_strength(game)
        if aggressive_action and strength >= self.POKERMASTER_PREFLOP_SHOVE_STRENGTH:
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="pokermaster_short_stack_preflop_pressure",
                    raise_amount=_recommended_raise_amount(game, buttons),
                )
            )

        if strength < self.POKERMASTER_PREFLOP_CALL_STRENGTH:
            return _log_decision(DecisionResult(action="FOLD", reason="pokermaster_short_stack_preflop_fold"))

        return None

    def _can_raise_small_bet_for_value(
        self,
        game: Game,
        *,
        equity: float,
        edge: float,
        to_call: float,
    ) -> bool:
        street = _game_street(game)
        threshold = self.SMALL_BET_RAISE_EQUITY_BY_STREET.get(street)
        if threshold is None:
            return False
        if equity < threshold or edge < self.SMALL_BET_RAISE_EDGE:
            return False
        pot = _as_positive_float(getattr(game.etat, "pot", None))
        if pot is None:
            return False
        return (to_call / pot) <= self.SMALL_BET_MAX_POT_RATIO

    def _should_fold_river_board_only_hand(self, game: Game, *, to_call: float) -> bool:
        if _game_street(game) != "RIVER":
            return False
        pot = _as_positive_float(getattr(game.etat, "pot", None))
        if pot is None or pot <= 0 or (to_call / pot) < 0.65:
            return False
        return _hero_uses_no_private_card(game)

    def _should_fold_river_big_bet_with_weak_showdown(self, game: Game, *, to_call: float) -> bool:
        if _game_street(game) != "RIVER":
            return False
        pot = _as_positive_float(getattr(game.etat, "pot", None))
        if pot is None or (to_call / pot) < self.RIVER_BIG_BET_MIN_POT_RATIO:
            return False
        equity_1v1 = _as_probability(getattr(game.etat, "chance_win_0", None))
        if equity_1v1 is None:
            return False
        return equity_1v1 < self.RIVER_BIG_BET_MIN_1V1_EQUITY

    def _pokermaster_free_raise_equity_threshold(self, game: Game) -> float:
        street = _game_street(game)
        return self.POKERMASTER_FREE_RAISE_EQUITY_BY_STREET.get(street, 0.78)

    def _pokermaster_should_fold_river_pressure(self, game: Game, *, equity: float, to_call: float) -> bool:
        if _game_street(game) != "RIVER":
            return False
        pot = _as_positive_float(getattr(game.etat, "pot", None))
        if pot is None or pot <= 0:
            return False
        return (to_call / pot) >= self.POKERMASTER_RIVER_PRESSURE_POT_RATIO and equity < self.POKERMASTER_RIVER_PRESSURE_MIN_EQUITY

    def _pokermaster_should_fold_postflop_tournament_pressure(
        self,
        game: Game,
        *,
        equity: float,
        to_call: float,
    ) -> bool:
        street = _game_street(game)
        threshold = self.POKERMASTER_POSTFLOP_PRESSURE_EQUITY_BY_STREET.get(street)
        if threshold is None or not self._pokermaster_late_stage_pressure(game, to_call=to_call):
            return False
        pot = _as_positive_float(getattr(game.etat, "pot", None))
        if pot is None or pot <= 0:
            return False
        pressure_ratio = to_call / pot
        return pressure_ratio >= 0.22 and equity < threshold

    def _pokermaster_late_stage_pressure(self, game: Game, *, to_call: float) -> bool:
        pot = _as_positive_float(getattr(game.etat, "pot", None)) or 0.0
        return to_call >= self.POKERMASTER_LATE_STAGE_MIN_CALL or pot >= self.POKERMASTER_LATE_STAGE_MIN_POT

    def _hero_preflop_strength(self, game: Game) -> float:
        cards = getattr(game.etat, "cards", None)
        if cards is None:
            return 0.0
        hero_cards = [getattr(card, "poker_card", None) for card in cards.me_cards()]
        strength = starting_hand_strength(hero_cards)
        return 0.0 if strength is None else strength


def _log_decision(result: DecisionResult) -> DecisionResult:
    LOGGER.info("DECISION action=%s reason=%s raise=%s", result.action, result.reason, result.raise_amount)
    return result


def _free_action_available(buttons) -> bool:
    has_free_action = getattr(buttons, "has_free_action", None)
    if callable(has_free_action):
        return bool(has_free_action())
    return any(
        getattr(button, "enabled", False) and getattr(button, "etat", "").lower() == "check"
        for button in _iter_buttons(buttons)
    )


def _aggressive_action_available(buttons) -> bool:
    has_aggressive_action = getattr(buttons, "has_aggressive_action", None)
    if callable(has_aggressive_action):
        return bool(has_aggressive_action())
    return any(
        getattr(button, "enabled", False) and getattr(button, "etat", "").lower() in {"mise", "relance", "all-in"}
        for button in _iter_buttons(buttons)
    )


def _has_explicit_active_buttons(buttons) -> bool:
    return any(getattr(button, "enabled", False) for button in _iter_buttons(buttons))


def _game_street(game: Game) -> str:
    return str(getattr(game, "street", "") or "").upper()


def _recommended_raise_amount(game: Game, buttons) -> Optional[float]:
    pot = _as_positive_float(getattr(game.etat, "pot", None))
    to_call = _call_button_value(buttons)
    amount = _pot_sized_raise_amount(pot=pot, to_call=to_call, street=_game_street(game))
    if amount is None:
        amount = _as_positive_float(getattr(game.etat, "montant_a_jouer", None))
    if amount is None:
        amount = _as_positive_float(getattr(game.etat, "Call_max", None))
    min_raise = _min_aggressive_button_value(buttons)
    if amount is None:
        return min_raise
    if min_raise is not None and not _looks_like_preset_button(min_raise, pot):
        amount = max(amount, min_raise)
    return _round_chip_amount(amount)


def _pot_sized_raise_amount(
    *,
    pot: Optional[float],
    to_call: float,
    street: str,
) -> Optional[float]:
    if pot is None or pot <= 0:
        return None
    if to_call > 0:
        ratio = 0.62 if street in {"FLOP", "TURN"} else 0.50
        return max(to_call * 3.0, pot * ratio)
    ratio_by_street = {
        "PREFLOP": 0.55,
        "FLOP": 0.66,
        "TURN": 0.66,
        "RIVER": 0.50,
    }
    return pot * ratio_by_street.get(street, 0.60)


def _call_button_value(buttons) -> float:
    value = _as_positive_float(getattr(buttons, "min_value", lambda: 0.0)())
    return value or 0.0


def _looks_like_preset_button(value: float, pot: Optional[float]) -> bool:
    return pot is not None and pot > 0 and value > pot * 2.5


def _round_chip_amount(amount: float) -> float:
    if amount >= 100:
        return float(round(amount / 20.0) * 20)
    if amount >= 20:
        return float(round(amount / 10.0) * 10)
    return float(round(amount, 2))


def _min_aggressive_button_value(buttons) -> Optional[float]:
    values = [
        value
        for button in _iter_buttons(buttons)
        if getattr(button, "enabled", False)
        and str(getattr(button, "etat", "")).lower() in {"mise", "relance", "all-in"}
        for value in [_as_positive_float(getattr(button, "value", None))]
        if value is not None
    ]
    return min(values) if values else None


def _as_positive_float(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _as_probability(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= number <= 1.0:
        return None
    return number


def _hero_uses_no_private_card(game: Game) -> bool:
    try:
        from pokereval.hand_evaluator import HandEvaluator
    except Exception:
        return False

    cards = getattr(game.etat, "cards", None)
    if cards is None:
        return False
    hero_cards = [getattr(card, "poker_card", None) for card in cards.me_cards()]
    board_cards = [
        getattr(card, "poker_card", None)
        for card in cards.board_cards()
        if getattr(card, "formatted", None)
    ]
    if len(hero_cards) != 2 or len(board_cards) != 5:
        return False
    if any(card is None for card in [*hero_cards, *board_cards]):
        return False
    return HandEvaluator.Seven.evaluate_rank([*hero_cards, *board_cards]) == HandEvaluator.Five.evaluate_rank(board_cards)


def _iter_buttons(buttons):
    try:
        return iter(buttons)
    except TypeError:
        return iter(())


__all__ = ["ActionType", "DecisionConfig", "DecisionResult", "Decision"]
