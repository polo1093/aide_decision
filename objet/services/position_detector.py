"""Automatic hero position inference from the live preflop table state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from objet.services.range_analyzer import Position, normalize_position


DEFAULT_POSITION: Position = "BTN"


@dataclass(frozen=True)
class PositionDetection:
    position: Position
    reason: str
    confidence: float


def detect_hero_position(game: object, *, fallback: str = DEFAULT_POSITION) -> PositionDetection:
    """Infer hero position from current preflop state.

    The project does not scan a dealer chip yet, so this uses available live
    signals: street, free preflop option, active opponents, and player states.
    """

    fallback_position = normalize_position(fallback) or DEFAULT_POSITION
    street = str(getattr(game, "street", "") or "").upper()
    if street != "PREFLOP":
        return PositionDetection(fallback_position, "not_preflop", 0.0)

    buttons = getattr(getattr(game, "table", None), "buttons", None)
    if _has_free_action(buttons):
        return PositionDetection("BB", "preflop_free_option", 0.95)

    players = list(_iter_players(getattr(getattr(game, "etat", None), "players", None)))
    active_players = [player for player in players if _is_active(player)]
    opponent_count = len(active_players)
    total_players = opponent_count + 1
    if total_players <= 1:
        return PositionDetection(fallback_position, "not_enough_active_players", 0.0)

    if total_players == 2:
        return PositionDetection("SB", "heads_up_paid_option", 0.80)

    pending_after_hero = sum(1 for player in active_players if _player_state(player) in {"play", "check"})
    position = _position_from_pending_after_hero(total_players, pending_after_hero)
    if position is None:
        return PositionDetection(fallback_position, "position_inference_unavailable", 0.0)

    confidence = 0.78 if pending_after_hero <= total_players - 2 else 0.65
    return PositionDetection(position, f"pending_after_hero_{pending_after_hero}", confidence)


def _position_from_pending_after_hero(total_players: int, pending_after_hero: int) -> Optional[Position]:
    open_positions_by_count: dict[int, tuple[Position, ...]] = {
        6: ("UTG", "MP", "CO", "BTN", "SB"),
        5: ("MP", "CO", "BTN", "SB"),
        4: ("CO", "BTN", "SB"),
        3: ("BTN", "SB"),
        2: ("SB",),
    }
    positions = open_positions_by_count.get(max(2, min(6, total_players)))
    if positions is None:
        return None
    max_pending = len(positions) - 1
    index = max_pending - max(0, min(max_pending, pending_after_hero))
    return positions[index]


def _has_free_action(buttons: object) -> bool:
    has_free_action = getattr(buttons, "has_free_action", None)
    if callable(has_free_action):
        return bool(has_free_action())
    return any(
        getattr(button, "enabled", False) and str(getattr(button, "etat", "")).lower() == "check"
        for button in _iter_buttons(buttons)
    )


def _iter_buttons(buttons: object):
    try:
        return iter(buttons)
    except TypeError:
        return iter(())


def _iter_players(players: object):
    try:
        return iter(players)
    except TypeError:
        return iter(())


def _is_active(player: object) -> bool:
    is_activate = getattr(player, "is_activate", None)
    if callable(is_activate):
        return bool(is_activate())
    return _player_state(player) in {"play", "check", "paid", "call", "paie", "raise", "relance", "mise", "all-in"}


def _player_state(player: object) -> str:
    return str(getattr(player, "etat", "") or "").strip().lower()


__all__ = ["DEFAULT_POSITION", "PositionDetection", "detect_hero_position"]
