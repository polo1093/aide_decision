"""Tests for ML dataset snapshot building."""
from __future__ import annotations

from types import SimpleNamespace

from objet.services.controller import ControllerViewState
from objet.services.ml_dataset import (
    DECISION_ENGINE_VERSION,
    LEGACY_RULES_VERSION,
    ML_DATASET_SCHEMA_VERSION,
    ML_DECISION_SNAPSHOT_TYPE,
    PREMIUM_MADE_HAND_FIX_ID,
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
    assert event["metadata"]["decision_engine_version"] == DECISION_ENGINE_VERSION
    assert event["metadata"]["legacy_rules_version"] == LEGACY_RULES_VERSION
    assert event["metadata"]["decision_engine_fix_id"] == PREMIUM_MADE_HAND_FIX_ID
    assert event["metadata"]["decision_engine_fix_date"] == "2026-05-24"
    assert "git_commit" in event["metadata"]
    assert event["labels"]["legacy_action"] == "CALL"
    assert event["labels"]["legacy_reason"] == "call_profitable_or_close"
    assert event["labels"]["final_action"] == "CALL"
    assert event["features"]["amount_unit"] == "big_blind"
    assert event["features"]["amount_unit_value"] == 0.02
    assert event["features"]["amount_unit_source"] == "preflop_to_call"
    assert event["features"]["pot_bb"] == 1.5
    assert event["features"]["to_call_bb"] == 1.0
    assert event["features"]["buttons"][1]["value_bb"] == 1.0
    assert event["features"]["players"][0]["stack_bb"] == 475.0
    assert event["labels"]["label_valid"] is True
    assert event["labels"]["label_exclusion_reason"] is None
    assert event["labels"]["known_bug_risk"] is False
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
    assert event["features"]["pot_bb"] is None
    assert event["features"]["to_call_bb"] is None
    assert event["confidence"]["pot_ocr"] is None
    assert event["quality_flags"]["hero_cards_uncertain"] is True
    assert event["quality_flags"]["amount_unit_missing"] is True
    assert event["labels"]["label_valid"] is False
    assert event["labels"]["label_exclusion_reason"] == "non_actionable_label"


def test_ml_decision_snapshot_exports_amounts_in_big_blinds_across_scales() -> None:
    micro_event = _scaled_amount_event(pot=0.03, to_call=0.02, raise_amount=0.06)
    chip_event = _scaled_amount_event(pot=150.0, to_call=100.0, raise_amount=300.0)

    assert micro_event["features"]["pot_bb"] == chip_event["features"]["pot_bb"] == 1.5
    assert micro_event["features"]["to_call_bb"] == chip_event["features"]["to_call_bb"] == 1.0
    assert micro_event["labels"]["legacy_raise_amount_bb"] == chip_event["labels"]["legacy_raise_amount_bb"] == 3.0


def test_ml_decision_snapshot_uses_explicit_big_blind_for_postflop_amounts() -> None:
    state = ControllerViewState(
        game_name="PMU",
        scan_count=3,
        scan_ok=True,
        scan_failures=0,
        street="TURN",
        decision_action="RAISE",
        decision_reason="protect_strong_hand_drawy_board",
        raise_amount=180.0,
        hero_state=["Ah", "Kd"],
        board_state=["Ad", "Kh", "9h", "2c"],
        player_active=1,
        pot=240.0,
        to_call=40.0,
        hero_position_confidence=0.7,
    )
    event = build_ml_decision_snapshot(
        game=SimpleNamespace(current_big_blind=20.0, table=SimpleNamespace(buttons=[])),
        view_state=state,
    )

    assert event["features"]["amount_unit_source"] == "explicit_current_big_blind"
    assert event["features"]["pot_bb"] == 12.0
    assert event["features"]["to_call_bb"] == 2.0
    assert event["labels"]["legacy_raise_amount_bb"] == 9.0


def test_ml_decision_snapshot_excludes_quality_risky_action_labels() -> None:
    event = build_ml_decision_snapshot(
        game=SimpleNamespace(table=SimpleNamespace(buttons=[])),
        view_state=ControllerViewState(
            game_name="PMU",
            scan_count=2,
            scan_ok=True,
            scan_failures=0,
            street="PREFLOP",
            decision_action="CALL",
            decision_reason="call_profitable_or_close",
            hero_state=["Ah", "Kd"],
            board_state=[None, None, None, None, None],
            player_active=None,
            pot=100.0,
            to_call=20.0,
        ),
    )

    assert event["labels"]["label_valid"] is False
    assert event["labels"]["label_exclusion_reason"] == "opponent_count_uncertain"


def _scaled_amount_event(*, pot: float, to_call: float, raise_amount: float):
    return build_ml_decision_snapshot(
        game=SimpleNamespace(table=SimpleNamespace(buttons=[])),
        view_state=ControllerViewState(
            game_name="PMU",
            scan_count=2,
            scan_ok=True,
            scan_failures=0,
            street="PREFLOP",
            decision_action="RAISE",
            decision_reason="pokercharts_preflop_aggressive",
            raise_amount=raise_amount,
            hero_state=["Ah", "Kd"],
            board_state=[],
            player_active=1,
            buttons=[f"B0 paie :{to_call}"],
            pot=pot,
            to_call=to_call,
            hero_position_confidence=0.7,
        ),
    )


def _player(*, name: str, state: str, active: bool, stack: float, stack_start: float):
    return SimpleNamespace(
        name=name,
        etat=state,
        active_at_start=True,
        fond=SimpleNamespace(amount=stack),
        fond_start_Party=stack_start,
        is_activate=lambda: active,
    )
