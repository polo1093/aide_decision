"""Tests for the optional poker-charts preflop chart integration."""
from __future__ import annotations

from objet.services.poker_charts import (
    PROVIDERS,
    get_chart,
    get_hand_action,
    normalize_cell,
    normalize_provider,
)


def test_normalize_single_action_cell() -> None:
    cell = normalize_cell("raise")

    assert cell.weight == 100
    assert cell.actions == {"raise": 100}
    assert cell.continue_frequency == 100
    assert cell.aggressive_frequency == 100
    assert cell.fold_frequency == 0


def test_normalize_split_cell_splits_actions_evenly() -> None:
    cell = normalize_cell(["raise", "fold"])

    assert cell.weight == 100
    assert cell.actions == {"raise": 50, "fold": 50}
    assert cell.continue_frequency == 50
    assert cell.aggressive_frequency == 50
    assert cell.fold_frequency == 50


def test_normalize_weighted_cell_calculates_effective_frequencies() -> None:
    cell = normalize_cell({"weight": 60, "actions": {"raise": 70, "call": 30}})

    assert cell.continue_frequency == 60
    assert cell.aggressive_frequency == 42
    assert cell.fold_frequency == 40


def test_lookup_provider_scenario_and_villain_chart() -> None:
    chart = get_chart("pekarstas", "BB", "vs-open", "BTN")
    action = get_hand_action("pekarstas", "BB", "vs-open", "AKs", "BTN")

    assert chart is not None
    assert action is not None
    assert action.continue_frequency == 100
    assert action.aggressive_frequency == 100


def test_gtowizard_stub_is_not_exposed_as_provider() -> None:
    assert "gtowizard-gg-rc" not in PROVIDERS
    assert normalize_provider("gtowizard-gg-rc") is None
    assert get_chart("gtowizard-gg-rc", "BTN", "RFI") is None


def test_missing_hand_in_existing_chart_defaults_to_fold() -> None:
    action = get_hand_action("greenline", "UTG", "RFI", "72o")

    assert action is not None
    assert action.continue_frequency == 0
    assert action.aggressive_frequency == 0
    assert action.fold_frequency == 100
