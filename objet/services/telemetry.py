"""Sauvegarde structuree des snapshots de jeu pour analyse future."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Callable, Optional


DEFAULT_TELEMETRY_DIR = Path("logs") / "telemetry"


@dataclass
class TelemetryRecorder:
    """Enregistre les donnees de jeu en JSONL, par main et par joueur."""

    root_dir: Path | str = DEFAULT_TELEMETRY_DIR
    game_name: str = "PMU"
    enabled: bool = True
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir)

    def record_cycle(self, *, game: Any, view_state: Any) -> Optional[dict[str, Any]]:
        """Sauve le snapshot courant et retourne l'evenement serialise."""

        if not self.enabled:
            return None

        event = self.build_cycle_event(game=game, view_state=view_state)
        self._append_jsonl(self._hand_path(event["hand_id"]), event)
        for player in event["players"]:
            player_event = {
                "type": "player_snapshot",
                "recorded_at": event["recorded_at"],
                "game": event["game"],
                "hand_id": event["hand_id"],
                "street": event["street"],
                "scan_count": event["scan_count"],
                "player": player,
                "decision": event["decision"],
                "metrics": event["metrics"],
            }
            self._append_jsonl(self._player_path(player["name"]), player_event)
        return event

    def build_cycle_event(self, *, game: Any, view_state: Any) -> dict[str, Any]:
        players = _players_snapshot(getattr(getattr(game, "table", None), "players", []))
        players_by_name = {player["name"]: player for player in players}
        hand_id = getattr(view_state, "hand_id", None) or getattr(game, "hand_id", None)

        return {
            "type": "cycle_snapshot",
            "recorded_at": self._recorded_at(),
            "game": self.game_name,
            "hand_id": hand_id,
            "street": getattr(view_state, "street", getattr(game, "street", "IDLE")),
            "scan_count": getattr(view_state, "scan_count", None),
            "status": getattr(view_state, "status", ""),
            "new_party_state": getattr(view_state, "new_party_state", None),
            "hero_scan": _list_value(getattr(view_state, "hero_scan", [])),
            "board_scan": _list_value(getattr(view_state, "board_scan", [])),
            "hero_state": _list_value(getattr(view_state, "hero_state", [])),
            "board_state": _list_value(getattr(view_state, "board_state", [])),
            "players": players,
            "players_by_name": players_by_name,
            "buttons": _list_value(getattr(view_state, "buttons", [])),
            "target_button": getattr(view_state, "target_button", None),
            "metrics": {
                "pot": getattr(view_state, "pot", None),
                "to_call": getattr(view_state, "to_call", None),
                "equity_table": getattr(view_state, "equity_table", None),
                "equity_1v1": getattr(view_state, "equity_1v1", None),
                "equity_required": getattr(view_state, "equity_required", None),
                "ev": getattr(view_state, "ev", None),
                "call_max": getattr(view_state, "call_max", None),
            },
            "decision": {
                "action": getattr(view_state, "decision_action", "WAIT"),
                "reason": getattr(view_state, "decision_reason", ""),
                "raise_amount": getattr(view_state, "raise_amount", None),
            },
        }

    def _recorded_at(self) -> str:
        current = self.clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.isoformat()

    def _hand_path(self, hand_id: Any) -> Path:
        hand_name = "unknown" if hand_id is None else str(hand_id)
        return self.root_dir / self.game_name / "hands" / f"hand_{_safe_filename(hand_name)}.jsonl"

    def _player_path(self, player_name: str) -> Path:
        return self.root_dir / self.game_name / "players" / f"{_safe_filename(player_name)}.jsonl"

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _players_snapshot(players: Any) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for index, player in enumerate(players, start=1):
        name = _player_name(player, index)
        stack = _stack_amount(player)
        stack_start = getattr(player, "fond_start_Party", None)
        stack_delta = None
        if stack is not None and stack_start not in (None, 0):
            stack_delta = stack - stack_start
        is_active = getattr(player, "is_activate", None)
        snapshot.append(
            {
                "seat": index,
                "name": name,
                "state": getattr(player, "etat", None),
                "active": bool(is_active()) if callable(is_active) else None,
                "active_at_start": getattr(player, "active_at_start", None),
                "stack": stack,
                "stack_start": stack_start,
                "stack_delta": stack_delta,
            }
        )
    return snapshot


def _player_name(player: Any, index: int) -> str:
    raw_name = getattr(player, "name", None)
    if raw_name is None:
        return f"J{index}"
    clean_name = str(raw_name).strip()
    return clean_name or f"J{index}"


def _stack_amount(player: Any) -> Optional[float]:
    fond = getattr(player, "fond", None)
    return getattr(fond, "amount", None)


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value)


def _safe_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", ascii_value).strip("._")
    return clean or "unknown"


__all__ = ["TelemetryRecorder", "DEFAULT_TELEMETRY_DIR"]
