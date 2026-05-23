"""Static preflop chart lookup helpers ported from AHTOOOXA/poker-charts.

The imported source is MIT licensed. Only static chart data and pure lookup
logic are integrated here; leaderboard, scraping, player, and UI assets are
intentionally excluded.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from pokereval.card import Card as PokerEvalCard

from objet.services.poker_charts_data import CHARTS
from objet.services.range_analyzer import Position, classify_hole_cards, normalize_position


Provider = Literal["pekarstas", "greenline"]
Scenario = Literal["RFI", "vs-open", "vs-3bet", "vs-4bet"]
Action = Literal["fold", "call", "raise", "allin"]
Cell = str | Sequence[str] | dict[str, object]

PROVIDERS: tuple[Provider, ...] = ("pekarstas", "greenline")
SCENARIOS: tuple[Scenario, ...] = ("RFI", "vs-open", "vs-3bet", "vs-4bet")
DEFAULT_PROVIDER: Provider = "pekarstas"
AGGRESSIVE_ACTIONS = frozenset({"raise", "allin"})


@dataclass(frozen=True)
class NormalizedCell:
    """Action weights for one chart cell."""

    weight: float
    actions: dict[Action, float]

    @property
    def continue_frequency(self) -> float:
        return self.weight * (
            (self.actions.get("call", 0.0)
            + self.actions.get("raise", 0.0)
            + self.actions.get("allin", 0.0))
            / 100.0
        )

    @property
    def aggressive_frequency(self) -> float:
        return self.weight * (
            (self.actions.get("raise", 0.0) + self.actions.get("allin", 0.0)) / 100.0
        )

    @property
    def fold_frequency(self) -> float:
        return max(0.0, 100.0 - self.continue_frequency)


@dataclass(frozen=True)
class PokerChartAction:
    """Decision-relevant chart lookup result for a starting hand."""

    provider: Provider
    scenario: Scenario
    hero_position: Position
    villain_position: Optional[Position]
    hand: str
    cell: NormalizedCell

    @property
    def continue_frequency(self) -> float:
        return self.cell.continue_frequency

    @property
    def aggressive_frequency(self) -> float:
        return self.cell.aggressive_frequency

    @property
    def fold_frequency(self) -> float:
        return self.cell.fold_frequency


def normalize_provider(provider: object) -> Optional[Provider]:
    text = str(provider or "").strip().lower()
    return text if text in PROVIDERS else None


def normalize_scenario(scenario: object) -> Optional[Scenario]:
    text = str(scenario or "").strip()
    aliases = {
        "rfi": "RFI",
        "open": "RFI",
        "raise_first_in": "RFI",
        "vs_open": "vs-open",
        "vs-open": "vs-open",
        "open_defense": "vs-open",
        "vs_3bet": "vs-3bet",
        "vs-3bet": "vs-3bet",
        "vs_4bet": "vs-4bet",
        "vs-4bet": "vs-4bet",
    }
    normalized = aliases.get(text.lower(), text)
    return normalized if normalized in SCENARIOS else None


def get_chart_key(hero: Position, scenario: Scenario, villain: Optional[Position] = None) -> str:
    return f"{hero}-{scenario}-{villain}" if villain else f"{hero}-{scenario}"


def get_chart(
    provider: object,
    hero_position: object,
    scenario: object,
    villain_position: object = None,
) -> Optional[dict[str, Cell]]:
    normalized_provider = normalize_provider(provider)
    hero = normalize_position(hero_position)
    normalized_scenario = normalize_scenario(scenario)
    villain = normalize_position(villain_position)
    if normalized_provider is None or hero is None or normalized_scenario is None:
        return None
    key = get_chart_key(hero, normalized_scenario, villain)
    chart = CHARTS.get(normalized_provider, {}).get(key)
    return chart if isinstance(chart, dict) else None


def get_hand_action(
    provider: object,
    hero_position: object,
    scenario: object,
    hand: str,
    villain_position: object = None,
) -> Optional[PokerChartAction]:
    normalized_provider = normalize_provider(provider)
    hero = normalize_position(hero_position)
    normalized_scenario = normalize_scenario(scenario)
    villain = normalize_position(villain_position)
    if normalized_provider is None or hero is None or normalized_scenario is None:
        return None

    chart = get_chart(normalized_provider, hero, normalized_scenario, villain)
    if chart is None:
        return None

    return PokerChartAction(
        provider=normalized_provider,
        scenario=normalized_scenario,
        hero_position=hero,
        villain_position=villain,
        hand=hand,
        cell=normalize_cell(chart.get(hand, "fold")),
    )


def get_cards_action(
    provider: object,
    hero_position: object,
    scenario: object,
    cards: Sequence[PokerEvalCard],
    villain_position: object = None,
) -> Optional[PokerChartAction]:
    hand = classify_hole_cards(cards)
    if hand is None:
        return None
    return get_hand_action(provider, hero_position, scenario, hand, villain_position)


def normalize_cell(cell: object) -> NormalizedCell:
    if isinstance(cell, str):
        action = _normalize_action(cell)
        if action is None:
            return NormalizedCell(weight=0.0, actions={})
        return NormalizedCell(weight=100.0, actions={action: 100.0})

    if isinstance(cell, (list, tuple)):
        actions = [_normalize_action(action) for action in cell]
        actions = [action for action in actions if action is not None]
        if not actions:
            return NormalizedCell(weight=0.0, actions={})
        if len(set(actions)) == 1:
            return NormalizedCell(weight=100.0, actions={actions[0]: 100.0})
        share = 100.0 / len(actions)
        weights: dict[Action, float] = {}
        for action in actions:
            weights[action] = weights.get(action, 0.0) + share
        return NormalizedCell(weight=100.0, actions=weights)

    if isinstance(cell, dict):
        weight = _as_percent(cell.get("weight"))
        raw_actions = cell.get("actions")
        actions: dict[Action, float] = {}
        if isinstance(raw_actions, dict):
            for raw_action, raw_frequency in raw_actions.items():
                action = _normalize_action(raw_action)
                if action is not None:
                    actions[action] = _as_percent(raw_frequency)
        return NormalizedCell(weight=weight, actions=actions)

    return NormalizedCell(weight=0.0, actions={})


def _normalize_action(action: object) -> Optional[Action]:
    text = str(action or "").strip().lower()
    return text if text in {"fold", "call", "raise", "allin"} else None


def _as_percent(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(100.0, max(0.0, number))


__all__ = [
    "DEFAULT_PROVIDER",
    "PROVIDERS",
    "SCENARIOS",
    "NormalizedCell",
    "PokerChartAction",
    "get_cards_action",
    "get_chart",
    "get_chart_key",
    "get_hand_action",
    "normalize_cell",
    "normalize_provider",
    "normalize_scenario",
]
