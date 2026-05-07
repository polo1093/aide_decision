"""Tests for controller view state formatting."""
from __future__ import annotations

from objet.services.controller import ControllerViewState


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
