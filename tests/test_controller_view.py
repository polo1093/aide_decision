"""Tests for controller view state formatting."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from objet.entities.buttons import Button, Buttons
from objet.services.controller import Controller, ControllerViewState, button_target_for_action


def test_failed_scan_keeps_legacy_text_output() -> None:
    state = ControllerViewState(
        game_name="PMU",
        scan_count=3,
        scan_ok=False,
        scan_failures=2,
    )

    assert state.to_text() == "don t find     Scan n°2"


def test_successful_view_state_contains_dashboard_fields() -> None:
    state = ControllerViewState(
        game_name="PMU",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        hand_id=4,
        street="FLOP",
        hero_state=["A♥", "K♦"],
        board_state=["2♣", "7♠", "10♥", None, None],
        player_start=5,
        player_active=3,
        pot=1.25,
        to_call=0.2,
        equity_table=0.54,
        decision_action="CALL",
        decision_reason="call_profitable_or_close",
    )

    text = state.to_text()

    assert "Jeu: PMU" in text
    assert "Street: FLOP" in text
    assert "Decision -> Action: CALL" in text


def test_call_targets_pay_button_with_coordinates() -> None:
    buttons = [
        _button("fold", enabled=True, bbox=(10, 20, 30, 40)),
        _button("paie", enabled=True, bbox=(50, 60, 70, 80), text="paie 0.02", value=0.02),
        _button("relance", enabled=True, bbox=(90, 100, 110, 120)),
    ]

    target = button_target_for_action(buttons, "CALL")

    assert target == {
        "index": 1,
        "label": "B1",
        "state": "paie",
        "text": "paie 0.02",
        "value": 0.02,
        "bbox": [50, 60, 70, 80],
    }


def test_raise_targets_first_available_aggressive_button() -> None:
    buttons = [
        _button("mise", enabled=False, bbox=(1, 2, 3, 4)),
        _button("mise", enabled=True, bbox=(5, 6, 7, 8)),
        _button("all-in", enabled=True, bbox=(9, 10, 11, 12)),
    ]

    target = button_target_for_action(buttons, "RAISE")

    assert target["state"] == "mise"
    assert target["bbox"] == [5, 6, 7, 8]


def test_wait_has_no_target_button() -> None:
    buttons = [_button("check", enabled=True, bbox=(1, 2, 3, 4))]

    assert button_target_for_action(buttons, "WAIT") is None


def test_controller_defaults_to_legacy_decision_mode() -> None:
    controller = Controller(
        telemetry_enabled=False,
        player_history_enabled=False,
    )

    assert controller.decision.config.mode == "legacy"


def test_controller_passes_pokermaster_decision_mode() -> None:
    controller = Controller(
        decision_mode="pokermaster",
        telemetry_enabled=False,
        player_history_enabled=False,
    )

    assert controller.decision.config.mode == "pokermaster"


def test_controller_rejects_pokercharts_as_standalone_decision_mode() -> None:
    with pytest.raises(ValueError):
        Controller(
            decision_mode="pokercharts",
            telemetry_enabled=False,
            player_history_enabled=False,
        )


def test_controller_sets_hero_position_on_game() -> None:
    controller = Controller(
        hero_position="CO",
        telemetry_enabled=False,
        player_history_enabled=False,
    )

    assert controller.hero_position == "CO"
    assert controller.game.range_position == "CO"
    assert controller.game.etat.range_position == "CO"

    controller.set_hero_position("SB")

    assert controller.hero_position == "SB"
    assert controller.game.range_position == "SB"
    assert controller.game.etat.range_position == "SB"


def test_controller_auto_detects_hero_position_before_decision() -> None:
    controller = Controller(
        hero_position="BTN",
        telemetry_enabled=False,
        player_history_enabled=False,
    )
    controller.game.street = "PREFLOP"
    controller.game.table.buttons = Buttons(button=[Button(enabled=True, etat="check", value=0.0)])

    controller.detect_hero_position()

    assert controller.hero_position == "BB"
    assert controller.game.range_position == "BB"
    assert controller.game.etat.range_position == "BB"
    assert controller.hero_position_reason == "preflop_free_option"


def test_controller_can_disable_auto_position_detection() -> None:
    controller = Controller(
        hero_position="CO",
        auto_hero_position=False,
        telemetry_enabled=False,
        player_history_enabled=False,
    )
    controller.game.street = "PREFLOP"
    controller.game.table.buttons = Buttons(button=[Button(enabled=True, etat="check", value=0.0)])

    controller.detect_hero_position()

    assert controller.hero_position == "CO"
    assert controller.game.range_position == "CO"


def _button(state: str, *, enabled: bool, bbox, text: str = "", value: float = 0.0):
    return SimpleNamespace(
        etat=state,
        enabled=enabled,
        coordonate=bbox,
        texte=text,
        value=value,
    )
