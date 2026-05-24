"""Tests for ML dataset snapshot building."""
from __future__ import annotations

from types import SimpleNamespace

from objet.services.controller import ControllerViewState
from objet.services.ml_dataset import (
    ML_DATASET_SCHEMA_VERSION,
    ML_DECISION_SNAPSHOT_TYPE,
    build_ml_decision_snapshot,
)


def test_ml_decision_snapshot_contains_version_type_labels_and_quality_flags() -> None:
    game = SimpleNamespace(
        hand_id=12,
        street="PREFLOP",
        table=SimpleNamespace(
            buttons=[
                SimpleNamespace(enabled=True, etat="fold", value=0.0, texte="fold", score=0.91),
                SimpleNamespace(enabled=True, etat="paie", value=0.02, texte="paie 0.02", score=0.82),
            ],
            players=[
                _player(name="Alice", state="fold", active=False, stack=9.5, stack_start=10.0),
                _player(name="Bob", state="paid", active=True, stack=6.8, stack_start=7.0),
            ],
            cards=SimpleNamespace(
                me_cards=lambda: [
                    SimpleNamespace(formatted="Ah", value_score=0.96, suit_score=0.95),
                    SimpleNamespace(formatted="Kd", value_score=0.94, suit_score=0.93),
                ],
                board_cards=lambda: [],
            ),
            pot=SimpleNamespace(amount=0.03),
        ),
        etat=SimpleNamespace(opponent_profiles=[]),
    )
    state = ControllerViewState(
        game_name="PMU",
        scan_count=7,
        scan_ok=True,
        scan_failures=0,
        hand_id=12,
        street="PREFLOP",
        status="ok",
        hero_scan=["Ah", "Kd"],
        hero_state=["Ah", "Kd"],
        board_scan=[None, None, None, None, None],
        board_state=[None, None, None, None, None],
        player_start=2,
        player_active=1,
        buttons=["B0 fold", "B1 paie :0.02"],
        pot=0.03,
        to_call=0.02,
        equity_table=0.42,
        equity_required=0.4,
        ev=0.001,
        call_max=0.021,
        decision_action="CALL",
        decision_reason="call_profitable_or_close",
        hero_position="BTN",
        hero_position_confidence=0.78,
    )

    event = build_ml_decision_snapshot(
        game=game,
        view_state=state,
        recorded_at="2026-05-24T14:15:00+00:00",
    )

    assert event["schema_version"] == ML_DATASET_SCHEMA_VERSION
    assert event["type"] == ML_DECISION_SNAPSHOT_TYPE
    assert event["labels"]["legacy_action"] == "CALL"
    assert event["labels"]["legacy_reason"] == "call_profitable_or_close"
    assert event["labels"]["final_action"] == "CALL"
    assert "quality_flags" in event
    assert event["quality_flags"]["hero_cards_uncertain"] is False
    assert event["confidence"]["hero_cards_min"] == 0.93


def test_ml_decision_snapshot_tolerates_missing_critical_fields() -> None:
    event = build_ml_decision_snapshot(
        game=SimpleNamespace(table=SimpleNamespace()),
        view_state=ControllerViewState(
            game_name="PMU",
            scan_count=1,
            scan_ok=True,
            scan_failures=0,
        ),
    )

    assert event["type"] == "ml_decision_snapshot"
    assert event["features"]["pot"] is None
    assert event["features"]["to_call"] is None
    assert event["confidence"]["pot_ocr"] is None
    assert event["quality_flags"]["hero_cards_uncertain"] is True


def _player(*, name: str, state: str, active: bool, stack: float, stack_start: float):
    return SimpleNamespace(
        name=name,
        etat=state,
        active_at_start=True,
        fond=SimpleNamespace(amount=stack),
        fond_start_Party=stack_start,
        is_activate=lambda: active,
    )
