"""Tests for structured telemetry persistence."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
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

    hand_events = _read_jsonl(_hand_path(tmp_path, "PMU", recorder.session_id, 12))
    assert len(hand_events) == 1
    assert hand_events[0]["type"] == "cycle_snapshot"
    assert hand_events[0]["metrics"]["to_call"] == 0.02
    assert hand_events[0]["players"][0]["name"] == "Alice"

    alice_events = _read_jsonl(_player_path(tmp_path, "PMU", recorder.session_id, "Alice"))
    fallback_events = _read_jsonl(_player_path(tmp_path, "PMU", recorder.session_id, "J2"))
    bob_events = _read_jsonl(_player_path(tmp_path, "PMU", recorder.session_id, "Bob_Smith"))
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


def test_telemetry_keeps_legacy_positional_clock_argument(tmp_path) -> None:
    clock = lambda: datetime(2026, 5, 13, 22, 15, tzinfo=timezone.utc)
    recorder = TelemetryRecorder(tmp_path, "PMU", True, clock)

    assert recorder.clock is clock
    assert recorder.ml_dataset_enabled is False
    assert recorder.session_id == "20260513_221500_000000"


def test_telemetry_separates_runs_by_session_id(tmp_path) -> None:
    first = TelemetryRecorder(root_dir=tmp_path, game_name="PMU", session_id="run_a")
    second = TelemetryRecorder(root_dir=tmp_path, game_name="PMU", session_id="run_b")
    state = ControllerViewState(
        game_name="PMU",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        hand_id=1,
        street="PREFLOP",
    )
    game = SimpleNamespace(hand_id=1, table=SimpleNamespace(players=[]))

    first.record_cycle(game=game, view_state=state)
    second.record_cycle(game=game, view_state=state)

    assert _hand_path(tmp_path, "PMU", "run_a", 1).exists()
    assert _hand_path(tmp_path, "PMU", "run_b", 1).exists()
    assert not (tmp_path / "PMU" / "hands" / "hand_1.jsonl").exists()


def test_default_telemetry_does_not_import_ml_dataset(tmp_path) -> None:
    sys.modules.pop("objet.services.ml_dataset", None)
    recorder = TelemetryRecorder(root_dir=tmp_path, game_name="PMU")

    event = recorder.record_cycle(
        game=SimpleNamespace(hand_id=12, table=SimpleNamespace(players=[])),
        view_state=ControllerViewState(
            game_name="PMU",
            scan_count=7,
            scan_ok=True,
            scan_failures=0,
            hand_id=12,
            street="PREFLOP",
        ),
    )

    assert event["type"] == "cycle_snapshot"
    assert "objet.services.ml_dataset" not in sys.modules


def test_telemetry_can_append_optional_ml_decision_snapshot(tmp_path) -> None:
    recorder = TelemetryRecorder(
        root_dir=tmp_path,
        game_name="PMU",
        ml_dataset_enabled=True,
        clock=lambda: datetime(2026, 5, 13, 22, 15, tzinfo=timezone.utc),
    )
    game = SimpleNamespace(
        hand_id=12,
        street="PREFLOP",
        table=SimpleNamespace(players=[]),
    )
    state = ControllerViewState(
        game_name="PMU",
        scan_count=7,
        scan_ok=True,
        scan_failures=0,
        hand_id=12,
        street="PREFLOP",
        status="ok",
        hero_state=["Ah", "Kd"],
        decision_action="CALL",
        decision_reason="call_profitable_or_close",
    )

    event = recorder.record_cycle(game=game, view_state=state)

    hand_events = _read_jsonl(_hand_path(tmp_path, "PMU", recorder.session_id, 12))
    assert event["type"] == "cycle_snapshot"
    assert hand_events[0]["type"] == "cycle_snapshot"
    assert hand_events[1]["type"] == "ml_decision_snapshot"
    assert hand_events[1]["schema_version"] == "ml_dataset_v1"
    assert hand_events[1]["labels"]["legacy_action"] == "CALL"


def test_optional_ml_event_failure_does_not_break_cycle_snapshot(tmp_path, monkeypatch) -> None:
    recorder = TelemetryRecorder(root_dir=tmp_path, game_name="PMU", ml_dataset_enabled=True)

    def fail_ml_event(**_):
        raise RuntimeError("boom")

    monkeypatch.setattr(recorder, "build_ml_decision_event", fail_ml_event)

    event = recorder.record_cycle(
        game=SimpleNamespace(hand_id=12, table=SimpleNamespace(players=[])),
        view_state=ControllerViewState(
            game_name="PMU",
            scan_count=7,
            scan_ok=True,
            scan_failures=0,
            hand_id=12,
            street="PREFLOP",
        ),
    )

    hand_events = _read_jsonl(_hand_path(tmp_path, "PMU", recorder.session_id, 12))
    assert event["type"] == "cycle_snapshot"
    assert [item["type"] for item in hand_events] == ["cycle_snapshot"]


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _hand_path(root, game: str, session_id: str, hand_id: int):
    return root / game / "sessions" / session_id / "hands" / f"hand_{hand_id}.jsonl"


def _player_path(root, game: str, session_id: str, player: str):
    return root / game / "sessions" / session_id / "players" / f"{player}.jsonl"
