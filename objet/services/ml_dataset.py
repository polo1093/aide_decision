"""Build optional ML dataset events from the current runtime snapshot."""
from __future__ import annotations

from typing import Any, Optional


ML_DATASET_SCHEMA_VERSION = "ml_dataset_v1"
ML_DECISION_SNAPSHOT_TYPE = "ml_decision_snapshot"
DEFAULT_DECISION_MODE = "legacy"
DEFAULT_LABEL_SOURCE = "legacy"


def build_ml_decision_snapshot(
    *,
    game: Any,
    view_state: Any,
    recorded_at: Optional[str] = None,
    decision_mode: str = DEFAULT_DECISION_MODE,
    label_source: str = DEFAULT_LABEL_SOURCE,
) -> dict[str, Any]:
    """Return a versioned ML dataset event without mutating runtime state."""

    hand_id = _value(view_state, "hand_id", _value(game, "hand_id"))
    scan_count = _value(view_state, "scan_count")
    game_name = _value(view_state, "game_name", _value(game, "game_name"))
    event = {
        "schema_version": ML_DATASET_SCHEMA_VERSION,
        "type": ML_DECISION_SNAPSHOT_TYPE,
        "snapshot_id": _snapshot_id(game_name, hand_id, scan_count),
        "recorded_at": recorded_at,
        "metadata": {
            "game": game_name,
            "hand_id": hand_id,
            "scan_count": scan_count,
            "street": _value(view_state, "street", _value(game, "street")),
            "status": _value(view_state, "status"),
            "decision_mode": decision_mode,
            "label_source": label_source,
            "new_party_state": _value(view_state, "new_party_state"),
        },
        "features": _features(game=game, view_state=view_state),
        "labels": _labels(view_state),
        "confidence": _confidence(game=game, view_state=view_state),
        "quality_flags": _quality_flags(game=game, view_state=view_state),
        "debug": _debug(view_state),
    }
    return event


def _features(*, game: Any, view_state: Any) -> dict[str, Any]:
    pot = _number_or_none(_value(view_state, "pot"))
    to_call = _number_or_none(_value(view_state, "to_call"))
    return {
        "hero_cards": _list_or_empty(_value(view_state, "hero_state")) or _list_or_empty(_value(view_state, "hero_scan")),
        "board_cards": _list_or_empty(_value(view_state, "board_state")) or _list_or_empty(_value(view_state, "board_scan")),
        "hero_position": _value(view_state, "hero_position"),
        "player_start": _value(view_state, "player_start"),
        "player_active": _value(view_state, "player_active"),
        "pot": pot,
        "to_call": to_call,
        "to_call_pot_ratio": _ratio(to_call, pot),
        "buttons": _buttons_snapshot(game=game, view_state=view_state),
        "buttons_active": _active_button_states(game=game, view_state=view_state),
        "has_check": _has_button_state(game=game, view_state=view_state, states={"check"}),
        "has_call": _has_button_state(game=game, view_state=view_state, states={"paie", "call"}),
        "has_raise": _has_button_state(game=game, view_state=view_state, states={"mise", "relance", "raise", "all-in"}),
        "players": _players_snapshot(game),
        "opponent_profiles": _opponent_profiles(game, view_state),
        "equity_table": _number_or_none(_value(view_state, "equity_table")),
        "equity_1v1": _number_or_none(_value(view_state, "equity_1v1")),
        "equity_required": _number_or_none(_value(view_state, "equity_required")),
        "ev": _number_or_none(_value(view_state, "ev")),
        "call_max": _number_or_none(_value(view_state, "call_max")),
    }


def _labels(view_state: Any) -> dict[str, Any]:
    legacy_action = _value(view_state, "decision_action", "WAIT")
    return {
        "legacy_action": legacy_action,
        "legacy_reason": _value(view_state, "decision_reason"),
        "legacy_raise_amount": _number_or_none(_value(view_state, "raise_amount")),
        "ml_action": None,
        "ml_confidence": None,
        "final_action": legacy_action,
        "fallback_reason": None,
    }


def _confidence(*, game: Any, view_state: Any) -> dict[str, Any]:
    table = _value(game, "table")
    cards = _value(table, "cards")
    hero_cards = _call_list(cards, "me_cards")
    board_cards = _call_list(cards, "board_cards")
    return {
        "hero_cards_min": _cards_min_confidence(hero_cards[:2]),
        "board_cards_min": _cards_min_confidence([card for card in board_cards if _value(card, "formatted") is not None]),
        "pot_ocr": _value(_value(table, "pot"), "confidence"),
        "to_call_ocr": _buttons_min_confidence(_iter_buttons(_value(table, "buttons"))),
        "buttons_min": _buttons_min_confidence(_iter_buttons(_value(table, "buttons"))),
        "hero_position": _number_or_none(_value(view_state, "hero_position_confidence")),
        "player_count": None,
    }


def _quality_flags(*, game: Any, view_state: Any) -> dict[str, bool]:
    hero_cards = _list_or_empty(_value(view_state, "hero_state")) or _list_or_empty(_value(view_state, "hero_scan"))
    board_cards = _list_or_empty(_value(view_state, "board_state")) or _list_or_empty(_value(view_state, "board_scan"))
    pot = _number_or_none(_value(view_state, "pot"))
    to_call = _number_or_none(_value(view_state, "to_call"))
    position_confidence = _number_or_none(_value(view_state, "hero_position_confidence"))

    flags = {
        "hero_cards_uncertain": len(hero_cards) < 2 or any(card in (None, "") for card in hero_cards[:2]),
        "board_uncertain": _board_is_uncertain(board_cards),
        "opponent_count_uncertain": _value(view_state, "player_active") is None,
        "pot_to_call_incoherent": _pot_to_call_incoherent(pot=pot, to_call=to_call),
        "buttons_incoherent": _buttons_incoherent(game=game, view_state=view_state),
        "hero_position_low_confidence": position_confidence is None or position_confidence < 0.5,
        "street_transient": _street_transient(view_state),
        "usable_for_training": False,
    }
    flags["usable_for_training"] = not any(
        flags[key]
        for key in (
            "hero_cards_uncertain",
            "board_uncertain",
            "opponent_count_uncertain",
            "pot_to_call_incoherent",
            "buttons_incoherent",
            "street_transient",
        )
    )
    return flags


def _debug(view_state: Any) -> dict[str, Any]:
    return {
        "hero_scan_raw": _list_or_empty(_value(view_state, "hero_scan")),
        "board_scan_raw": _list_or_empty(_value(view_state, "board_scan")),
        "hero_state_raw": _list_or_empty(_value(view_state, "hero_state")),
        "board_state_raw": _list_or_empty(_value(view_state, "board_state")),
        "button_texts_raw": _list_or_empty(_value(view_state, "buttons")),
        "target_button": _value(view_state, "target_button"),
        "scan_status": _value(view_state, "status"),
        "decision_reason": _value(view_state, "decision_reason"),
    }


def _buttons_snapshot(*, game: Any, view_state: Any) -> list[dict[str, Any]]:
    buttons = list(_iter_buttons(_value(_value(game, "table"), "buttons")))
    if buttons:
        return [
            {
                "index": index,
                "enabled": bool(_value(button, "enabled", False)),
                "state": _value(button, "etat", _value(button, "state")),
                "value": _number_or_none(_value(button, "value")),
                "text": _value(button, "texte", _value(button, "text")),
                "confidence": _value(button, "score"),
            }
            for index, button in enumerate(buttons)
        ]
    return [
        {
            "index": index,
            "enabled": bool(text),
            "state": _button_state_from_text(text),
            "value": _button_value_from_text(text),
            "text": text,
            "confidence": None,
        }
        for index, text in enumerate(_list_or_empty(_value(view_state, "buttons")))
        if text
    ]


def _active_button_states(*, game: Any, view_state: Any) -> list[Any]:
    return [
        button["state"]
        for button in _buttons_snapshot(game=game, view_state=view_state)
        if button["enabled"] and button["state"]
    ]


def _has_button_state(*, game: Any, view_state: Any, states: set[str]) -> Optional[bool]:
    buttons = _buttons_snapshot(game=game, view_state=view_state)
    if not buttons:
        return None
    expected = {state.lower() for state in states}
    return any(
        button["enabled"] and str(button["state"] or "").lower() in expected
        for button in buttons
    )


def _players_snapshot(game: Any) -> list[dict[str, Any]]:
    players = _iter_players(_value(_value(game, "table"), "players"))
    return [
        {
            "seat": index,
            "name": _value(player, "name"),
            "state": _value(player, "etat"),
            "active": _call_bool(player, "is_activate"),
            "active_at_start": _value(player, "active_at_start"),
            "stack": _number_or_none(_value(_value(player, "fond"), "amount")),
            "stack_start": _number_or_none(_value(player, "fond_start_Party")),
        }
        for index, player in enumerate(players, start=1)
    ]


def _opponent_profiles(game: Any, view_state: Any) -> list[dict[str, Any]] | list[Any]:
    profiles = _list_or_empty(_value(_value(game, "etat"), "opponent_profiles"))
    if profiles:
        return [
            {
                "name": _value(profile, "name"),
                "looseness": _number_or_none(_value(profile, "looseness")),
                "aggression": _number_or_none(_value(profile, "aggression")),
                "action": _value(profile, "action"),
                "confidence": _number_or_none(_value(profile, "confidence")),
            }
            for profile in profiles
        ]
    return _list_or_empty(_value(view_state, "opponent_profiles"))


def _cards_min_confidence(cards: list[Any]) -> Optional[float]:
    scores: list[float] = []
    for card in cards:
        for attr in ("value_score", "suit_score"):
            score = _number_or_none(_value(card, attr))
            if score is not None:
                scores.append(score)
    return min(scores) if scores else None


def _buttons_min_confidence(buttons: list[Any]) -> Optional[float]:
    scores = [
        score
        for button in buttons
        for score in [_number_or_none(_value(button, "score"))]
        if score is not None
    ]
    return min(scores) if scores else None


def _board_is_uncertain(board_cards: list[Any]) -> bool:
    visible = [card for card in board_cards if card not in (None, "")]
    return len(visible) not in (0, 3, 4, 5)


def _pot_to_call_incoherent(*, pot: Optional[float], to_call: Optional[float]) -> bool:
    if pot is None or to_call is None:
        return True
    if pot < 0 or to_call < 0:
        return True
    return pot > 0 and to_call > pot * 10


def _buttons_incoherent(*, game: Any, view_state: Any) -> bool:
    buttons = _buttons_snapshot(game=game, view_state=view_state)
    active_states = {str(button["state"] or "").lower() for button in buttons if button["enabled"]}
    if not active_states:
        return True
    return "check" in active_states and ("paie" in active_states or "call" in active_states)


def _street_transient(view_state: Any) -> bool:
    street = str(_value(view_state, "street", "") or "").upper()
    board_cards = _list_or_empty(_value(view_state, "board_state")) or _list_or_empty(_value(view_state, "board_scan"))
    visible = sum(1 for card in board_cards if card not in (None, ""))
    expected = {"PREFLOP": 0, "FLOP": 3, "TURN": 4, "RIVER": 5}.get(street)
    return expected is not None and visible not in (expected, 0) and visible not in (3, 4, 5)


def _snapshot_id(game_name: Any, hand_id: Any, scan_count: Any) -> Optional[str]:
    if game_name is None or hand_id is None or scan_count is None:
        return None
    return f"{game_name}:{hand_id}:{scan_count}"


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _button_state_from_text(text: Any) -> Optional[str]:
    lowered = str(text or "").lower()
    for state in ("check", "paie", "call", "relance", "raise", "mise", "fold", "all-in"):
        if state in lowered:
            return "paie" if state == "call" else "relance" if state == "raise" else state
    return None


def _button_value_from_text(text: Any) -> Optional[float]:
    import re

    matches = re.findall(r"[-+]?\d+(?:[.,]\d+)?", str(text or ""))
    if not matches:
        return None
    try:
        return float(matches[-1].replace(",", "."))
    except ValueError:
        return None


def _value(source: Any, attr: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(attr, default)
    return getattr(source, attr, default)


def _number_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list_or_empty(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except TypeError:
        return []


def _call_list(source: Any, method_name: str) -> list[Any]:
    method = _value(source, method_name)
    if not callable(method):
        return []
    try:
        return list(method())
    except TypeError:
        return []


def _call_bool(source: Any, method_name: str) -> Optional[bool]:
    method = _value(source, method_name)
    if not callable(method):
        return None
    return bool(method())


def _iter_buttons(buttons: Any) -> list[Any]:
    return _list_or_empty(buttons)


def _iter_players(players: Any) -> list[Any]:
    return _list_or_empty(players)


__all__ = [
    "DEFAULT_DECISION_MODE",
    "DEFAULT_LABEL_SOURCE",
    "ML_DATASET_SCHEMA_VERSION",
    "ML_DECISION_SNAPSHOT_TYPE",
    "build_ml_decision_snapshot",
]
