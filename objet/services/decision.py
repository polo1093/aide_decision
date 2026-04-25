"""Decision helper to recommend a poker action for the hero."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from objet.entities.card import Card, CardsState
from objet.services.game import Game

ActionType = Literal["WAIT", "FOLD", "CALL", "CHECK", "RAISE"]


@dataclass(frozen=True)
class DecisionResult:
    """Immutable result describing the recommended poker action."""

    action: ActionType
    reason: str
    raise_amount: Optional[float] = None


class Decision:
    """Simple, fail-fast decision engine for the hero."""

    FOLD_THRESHOLD: float = 0.01

    def decide(self, game: Game) -> DecisionResult:
        """Return the recommended action for the hero based on the current state."""
        if getattr(game, "new_party_detected", False):
            return DecisionResult(action="WAIT", reason="new_party_pending_reset")

        if not game.etat.cards.is_ready_for_cal():
            return DecisionResult(action="WAIT", reason="hero_cards_not_detected_yet")

        buttons = getattr(game.table, "buttons", None)
        if buttons is None or not buttons.one_is_activate():
            return DecisionResult(action="WAIT", reason="not_buttons")

        min_value = buttons.min_value()
        Call_max = game.etat.Call_max

        if Call_max < min_value - self.FOLD_THRESHOLD:
            return DecisionResult(action="CHECK", reason="chance_win_below_fold_threshold")

        if Call_max > min_value + self.FOLD_THRESHOLD * 5 :
            return DecisionResult(action="RAISE", reason="chance_win_between_thresholds")
        
    
        return DecisionResult(
            action="CALL",
            reason="chance_win_above_aggressive_threshold",
            # raise_amount=raise_amount,
        )

 





__all__ = ["ActionType", "DecisionResult", "Decision"]
