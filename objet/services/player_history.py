"""Long-term player tendency storage.

The live scan gives a useful instant read of each opponent.  This module keeps a
small durable memory per player and blends it back into opponent profiles so the
equity simulator can react to observed habits over many hands.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Callable, Optional, Sequence

from objet.services.equity import OpponentProfile, opponent_profiles_from_players


DEFAULT_PLAYER_HISTORY_DIR = Path("logs") / "player_history"
PLAYER_HISTORY_VERSION = 1


@dataclass
class PlayerHistoryStore:
    root_dir: Path | str = DEFAULT_PLAYER_HISTORY_DIR
    game_name: str = "PMU"
    enabled: bool = True
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    _data: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _loaded: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir)

    @property
    def path(self) -> Path:
        return player_history_path(self.game_name, root_dir=self.root_dir)

    def load(self) -> dict[str, Any]:
        if self._loaded:
            return self._data

        if not self.path.exists():
            self._data = self._empty_data()
            self._loaded = True
            return self._data

        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if not isinstance(data, dict):
            data = self._empty_data()
        data.setdefault("version", PLAYER_HISTORY_VERSION)
        data.setdefault("game", self.game_name)
        players = data.setdefault("players", {})
        if not isinstance(players, dict):
            data["players"] = {}

        self._data = data
        self._loaded = True
        return self._data

    def save(self) -> None:
        if not self.enabled:
            return
        data = self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")

    def clear(self) -> Path:
        self._data = self._empty_data()
        self._loaded = True
        if self.path.exists():
            self.path.unlink()
        return self.path

    def record_players(self, players: Sequence[object], *, hand_id: Any) -> None:
        if not self.enabled:
            return

        changed = False
        hand_key = "unknown" if hand_id is None else str(hand_id)
        recorded_at = self._recorded_at()
        data = self.load()
        bucket = data.setdefault("players", {})

        for index, player in enumerate(players, start=1):
            name = _player_name(player, index)
            stats = bucket.setdefault(name, _empty_player_stats(name=name, seat=index))
            changed |= _touch_player_stats(
                stats=stats,
                player=player,
                hand_key=hand_key,
                recorded_at=recorded_at,
                seat=index,
            )

        if changed:
            self.save()

    def opponent_profiles_from_players(self, players: Sequence[object]) -> list[OpponentProfile]:
        base_profiles = opponent_profiles_from_players(players)
        return self.adjust_profiles(players, base_profiles)

    def adjust_profiles(
        self,
        players: Sequence[object],
        base_profiles: Sequence[OpponentProfile],
    ) -> list[OpponentProfile]:
        if not self.enabled:
            return list(base_profiles)

        data = self.load()
        stats_by_name = data.get("players", {})
        adjusted: list[OpponentProfile] = []

        active_index = 0
        for index, player in enumerate(players, start=1):
            is_active = getattr(player, "is_activate", None)
            if callable(is_active) and not is_active():
                continue
            if active_index >= len(base_profiles):
                break

            base = base_profiles[active_index]
            active_index += 1
            name = _player_name(player, index)
            stats = stats_by_name.get(name)
            history_profile = _profile_from_stats(name, stats)
            if history_profile is None:
                adjusted.append(base)
                continue

            confidence = _clamp(history_profile.confidence, 0.0, 0.65)
            adjusted.append(
                OpponentProfile(
                    name=base.name,
                    looseness=_blend(base.looseness, history_profile.looseness, confidence),
                    aggression=_blend(base.aggression, history_profile.aggression, confidence),
                    action=base.action,
                    confidence=confidence,
                )
            )

        if len(base_profiles) > len(adjusted):
            adjusted.extend(base_profiles[len(adjusted) :])
        return adjusted

    def player_count(self) -> int:
        players = self.load().get("players", {})
        return len(players) if isinstance(players, dict) else 0

    def stats_for(self, name: str) -> Optional[dict[str, Any]]:
        players = self.load().get("players", {})
        stats = players.get(name) if isinstance(players, dict) else None
        return dict(stats) if isinstance(stats, dict) else None

    def _empty_data(self) -> dict[str, Any]:
        return {
            "version": PLAYER_HISTORY_VERSION,
            "game": self.game_name,
            "players": {},
        }

    def _recorded_at(self) -> str:
        current = self.clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.isoformat()


def player_history_path(game_name: str, *, root_dir: Path | str = DEFAULT_PLAYER_HISTORY_DIR) -> Path:
    return Path(root_dir) / f"{_safe_filename(game_name)}.json"


def _touch_player_stats(
    *,
    stats: dict[str, Any],
    player: object,
    hand_key: str,
    recorded_at: str,
    seat: int,
) -> bool:
    changed = False
    stats["name"] = stats.get("name") or _player_name(player, seat)
    stats["seat"] = seat
    stats["last_seen"] = recorded_at

    if stats.get("last_hand_id") != hand_key:
        stats["hands"] = int(stats.get("hands", 0)) + 1
        if bool(getattr(player, "active_at_start", True)):
            stats["dealt_hands"] = int(stats.get("dealt_hands", 0)) + 1
        is_active = getattr(player, "is_activate", None)
        if callable(is_active) and is_active():
            stats["active_hands"] = int(stats.get("active_hands", 0)) + 1
        stats["last_hand_id"] = hand_key
        stats["last_invested_hand_id"] = hand_key
        stats["last_invested_amount"] = 0.0
        changed = True

    action_bucket = _action_bucket(getattr(player, "etat", None))
    if action_bucket:
        last_action_key = f"last_{action_bucket}_hand_id"
        if stats.get(last_action_key) != hand_key:
            stats[action_bucket] = int(stats.get(action_bucket, 0)) + 1
            stats[last_action_key] = hand_key
            changed = True

    invested = _invested_amount(player)
    if invested is not None:
        previous = _as_float(stats.get("last_invested_amount")) or 0.0
        if stats.get("last_invested_hand_id") != hand_key:
            previous = 0.0
            stats["last_invested_hand_id"] = hand_key
        if invested > previous:
            stats["invested_total"] = (_as_float(stats.get("invested_total")) or 0.0) + (invested - previous)
            stats["last_invested_amount"] = invested
            changed = True

    return changed


def _empty_player_stats(*, name: str, seat: int) -> dict[str, Any]:
    return {
        "name": name,
        "seat": seat,
        "hands": 0,
        "dealt_hands": 0,
        "active_hands": 0,
        "plays": 0,
        "checks": 0,
        "calls": 0,
        "raises": 0,
        "folds": 0,
        "invested_total": 0.0,
    }


def _profile_from_stats(name: str, stats: Any) -> Optional[OpponentProfile]:
    if not isinstance(stats, dict):
        return None

    hands = max(0, int(stats.get("hands", 0) or 0))
    if hands <= 0:
        return None

    calls = max(0, int(stats.get("calls", 0) or 0))
    raises = max(0, int(stats.get("raises", 0) or 0))
    checks = max(0, int(stats.get("checks", 0) or 0))
    plays = max(0, int(stats.get("plays", 0) or 0))
    folds = max(0, int(stats.get("folds", 0) or 0))
    active_hands = max(0, int(stats.get("active_hands", 0) or 0))

    vpip = min(1.0, (calls + raises) / max(1, hands))
    active_rate = min(1.0, active_hands / max(1, hands))
    passive_rate = min(1.0, (checks + plays) / max(1, hands))
    fold_rate = min(1.0, folds / max(1, hands))

    action_total = max(1, calls + raises + checks + folds)
    raise_share = raises / action_total
    invested_pressure = min(0.10, ((_as_float(stats.get("invested_total")) or 0.0) / max(1, hands)) * 0.02)

    looseness = _clamp(0.24 + 0.52 * vpip + 0.18 * active_rate + 0.08 * passive_rate - 0.18 * fold_rate, 0.08, 0.95)
    aggression = _clamp(0.20 + 0.72 * raise_share + 0.12 * vpip + invested_pressure, 0.08, 0.95)
    confidence = min(0.65, hands / 60.0)

    return OpponentProfile(
        name=name,
        looseness=looseness,
        aggression=aggression,
        action="history",
        confidence=confidence,
    )


def _action_bucket(action: object) -> Optional[str]:
    text = str(action or "").strip().lower()
    if text in {"paid", "call", "paie"}:
        return "calls"
    if text in {"raise", "relance", "mise", "all-in"}:
        return "raises"
    if text in {"check"}:
        return "checks"
    if text in {"fold"}:
        return "folds"
    if text in {"play"}:
        return "plays"
    return None


def _player_name(player: object, index: int) -> str:
    raw_name = getattr(player, "name", None)
    clean = str(raw_name or "").strip()
    return clean or f"J{index}"


def _invested_amount(player: object) -> Optional[float]:
    start_amount = _as_float(getattr(player, "fond_start_Party", None))
    current_amount = _as_float(getattr(getattr(player, "fond", None), "amount", None))
    if start_amount is None or current_amount is None or start_amount <= 0:
        return None
    return max(0.0, start_amount - current_amount)


def _as_float(value: object) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _blend(current: float, history: float, weight: float) -> float:
    return _clamp((float(current) * (1.0 - weight)) + (float(history) * weight), 0.0, 1.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _safe_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", ascii_value).strip("._")
    return clean or "unknown"


__all__ = [
    "DEFAULT_PLAYER_HISTORY_DIR",
    "PLAYER_HISTORY_VERSION",
    "PlayerHistoryStore",
    "player_history_path",
]
