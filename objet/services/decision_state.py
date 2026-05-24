"""Plain data contracts consumed by decision engines."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


ActionType = Literal["WAIT", "FOLD", "CALL", "CHECK", "RAISE"]


@dataclass(frozen=True)
class ButtonState:
    """Normalized action button state without OCR or UI dependencies."""

    enabled: bool
    state: str
    value: float = 0.0
    text: str = ""

    @property
    def etat(self) -> str:
        """Compatibility name used by the current decision helpers."""
        return self.state


@dataclass(frozen=True)
class HeroPositionInfo:
    """Hero position metadata used by preflop strategy."""

    position: str = "BTN"
    reason: str = ""
    confidence: Optional[float] = None


@dataclass(frozen=True)
class DecisionInput:
    """Stable poker state passed to a decision engine."""

    new_party_detected: bool = False
    street: str = "IDLE"
    hero_cards: list[Optional[str]] = field(default_factory=list)
    board_cards: list[Optional[str]] = field(default_factory=list)
    strategy_hero_cards: list[Optional[str]] = field(default_factory=list)
    buttons: list[ButtonState] = field(default_factory=list)
    pot: Optional[float] = None
    to_call: float = 0.0
    equity: Optional[float] = None
    equity_1v1: Optional[float] = None
    equity_required: Optional[float] = None
    call_max: float = 0.0
    amount_to_play: Optional[float] = None
    hero_position: HeroPositionInfo = field(default_factory=HeroPositionInfo)
    pokercharts_provider: Optional[str] = None
    preflop_scenario: Optional[str] = None
    villain_position: Optional[str] = None


@dataclass(frozen=True)
class DecisionOutput:
    """Decision engine output shown by the UI and logs."""

    action: ActionType
    reason: str
    raise_amount: Optional[float] = None


__all__ = [
    "ActionType",
    "ButtonState",
    "DecisionInput",
    "DecisionOutput",
    "HeroPositionInfo",
]
