"""Decision helper to recommend a poker action for the hero."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from objet.services.game import Game
from objet.utils.logging_config import get_logger

ActionType = Literal["WAIT", "FOLD", "CALL", "CHECK", "RAISE"]
LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class DecisionResult:
    """Immutable result describing the recommended poker action."""

    action: ActionType
    reason: str
    raise_amount: Optional[float] = None


class Decision:
    """Simple, fail-fast decision engine for the hero."""

    # Monte Carlo has variance, so a tiny positive edge is not enough to raise.
    FOLD_EDGE: float = -0.03
    RAISE_EDGE: float = 0.08
    FREE_RAISE_EQUITY: float = 0.65

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
            if aggressive_action and equity >= self.FREE_RAISE_EQUITY:
                return _log_decision(DecisionResult(action="RAISE", reason="free_option_strong_equity"))
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

        if edge >= self.RAISE_EDGE:
            return _log_decision(DecisionResult(action="RAISE", reason="positive_edge_raise"))
        
        return _log_decision(DecisionResult(action="CALL", reason="call_profitable_or_close"))


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


def _iter_buttons(buttons):
    try:
        return iter(buttons)
    except TypeError:
        return iter(())


__all__ = ["ActionType", "DecisionResult", "Decision"]
