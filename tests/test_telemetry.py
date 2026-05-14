"""Tests for structured telemetry persistence."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace

from objet.services.controller import ControllerViewState
from objet.services.telemetry import TelemetryRecorder


class DummyPlayer:
    def __init__(
        self,
        *,
        name: str | None,
        state: str,
        stack: float | None,
        stack_start: float | None,
        active: bool,
        active_at_start: bool = True,
    ) -> None:
        self.name = name
        self.etat = state
        self.fond = SimpleNamespace(amount=stack)
        self.fond_start_Party = stack_start
        self._active = active
        self.active_at_start = active_at_start

    def is_activate(self) -> bool:
        return self._active


def test_telemetry_saves_hand_snapshot_and_player_files_by_name(tmp_path) -> None:
    recorder = TelemetryRecorder(
        root_dir=tmp_path,
        game_name="PMU",
        clock=lambda: datetime(2026, 5, 13, 22, 15, tzinfo=timezone.utc),
    )
    game = SimpleNamespace(
        hand_id=12,
        street="PREFLOP",
        table=SimpleNamespace(
            players=[
                DummyPlayer(name="Alice", state="fold", stack=9.5, stack_start=10.0, active=False),
                DummyPlayer(name=None, state="play", stack=8.0, stack_start=8.0, active=True),
                DummyPlayer(name="Bob Smith", state="paid", stack=6.8, stack_start=7.0, active=True),
            ]
        ),
    )
    state = ControllerViewState(
        game_name="PMU",
        scan_count=7,
        scan_ok=True,
        scan_failures=0,
        hand_id=12,
        street="PREFLOP",
        status="ok",
        hero_scan=["7d", "5c"],
        board_scan=[None, None, None, None, None],
        hero_state=["7d", "5c"],
        board_state=[None, None, None, None, None],
        buttons=["B0 fold", "B1 paie :0.02"],
        pot=0.03,
        to_call=0.02,
        equity_table=0.2,
        equity_required=0.4,
        ev=-0.01,
        call_max=0.007,
        decision_action="FOLD",
        decision_reason="negative_call_ev",
    )

    event = recorder.record_cycle(game=game, view_state=state)

    assert event["players_by_name"]["Alice"]["state"] == "fold"
    assert event["players_by_name"]["Alice"]["stack_delta"] == -0.5
    assert event["players_by_name"]["J2"]["active"] is True
    assert event["players_by_name"]["Bob Smith"]["state"] == "paid"
    assert event["decision"] == {
        "action": "FOLD",
        "reason": "negative_call_ev",
        "raise_amount": None,
    }

    hand_events = _read_jsonl(tmp_path / "PMU" / "hands" / "hand_12.jsonl")
    assert len(hand_events) == 1
    assert hand_events[0]["type"] == "cycle_snapshot"
    assert hand_events[0]["metrics"]["to_call"] == 0.02
    assert hand_events[0]["players"][0]["name"] == "Alice"

    alice_events = _read_jsonl(tmp_path / "PMU" / "players" / "Alice.jsonl")
    fallback_events = _read_jsonl(tmp_path / "PMU" / "players" / "J2.jsonl")
    bob_events = _read_jsonl(tmp_path / "PMU" / "players" / "Bob_Smith.jsonl")
    assert alice_events[0]["player"]["name"] == "Alice"
    assert fallback_events[0]["player"]["name"] == "J2"
    assert bob_events[0]["player"]["name"] == "Bob Smith"


def test_disabled_telemetry_does_not_write_files(tmp_path) -> None:
    recorder = TelemetryRecorder(root_dir=tmp_path, enabled=False)

    result = recorder.record_cycle(
        game=SimpleNamespace(table=SimpleNamespace(players=[])),
        view_state=ControllerViewState(game_name="PMU", scan_count=1, scan_ok=True, scan_failures=0),
    )

    assert result is None
    assert not list(tmp_path.rglob("*"))


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
